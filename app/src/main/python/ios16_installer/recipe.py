"""Runtime transformation of privately downloaded Apple data and owned helper files."""
from pathlib import Path
import plistlib
import stat
from .images import Tree
from .safety import Hooks, safe_relative, checked_path
from .resources import AUDIO_CONFIG_NAME, AUDIO_CONFIG_PATH, AUDIO_EXECUTABLE_PATH

DEFAULT_JOBS = ('com.apple.notifyd com.apple.cfprefsd.xpc.daemon com.apple.cfprefsd.xpc.daemon.system '
 'com.apple.logd com.apple.syslogd com.apple.distnoted.xpc.daemon com.apple.diagnosticd com.apple.fseventsd '
 'com.apple.containermanagerd com.apple.containermanagerd.system com.apple.runningboardd com.apple.backboardd '
 'com.apple.mobile.usermanagerd com.apple.mobilegestalt.xpc com.apple.lsd com.apple.powerd com.apple.analyticsd '
 'com.apple.logd_helper com.apple.iconservices.iconservicesagent com.apple.pluginkit.pkd com.apple.SpringBoard '
 'com.apple.chronod com.apple.wifid').split()
DENY = ('watchdog', 'CommCenter', 'wifi', 'WiFi', 'bluetooth', 'BTServer', 'locationd', 'softwareupdate',
 'datamigrator', 'backupd', 'thermalmonitord', 'keybagd', 'nfcd', 'biometrickitd', 'pearld', 'obliterat',
 'storage_mounter', 'com.apple.fud', 'sepd', 'seputil', 'camera', 'ReportCrash', 'osanalytics', 'lockdown',
 'audio', 'jetsamproperties', 'purplebuddy', 'restore', 'usb', 'accessoryd', 'mobileassetd', 'bird',
 'homed', 'routined', 'duetexpertd', 'com.apple.dmd', 'syncdefaultsd', 'photoanalysisd', 'avconferenced')

def generated_file(tree, generated, path, content, mode=0o644):
    target = checked_path(generated, path); target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content); tree.file(path, target, mode)

def var_skeleton(rows):
    directories = {}; links = {}
    for row in rows:
        if not (row.path == 'private/var' or row.path.startswith('private/var/')) or row.path.startswith(
                ('private/var/staged_system_apps', 'private/var/MobileAsset/')): continue
        if stat.S_ISDIR(row.mode): directories['/' + row.path] = (stat.S_IMODE(row.mode), row.uid, row.gid)
        elif stat.S_ISLNK(row.mode): links['/' + row.path] = row.target
    extras = {'db/uuidtext': (0o755,272,272), 'db/diagnostics/timesync': (0o755,272,272)}
    for path in ('containers', 'containers/Data', 'containers/Shared', 'containers/Bundle'):
        extras[path] = (0o755,0,0)
    for path in ('Containers', 'Containers/Data', 'Containers/Shared', 'Library/Caches', 'Library/Preferences', 'Library/Logs'):
        extras['mobile/' + path] = (0o755,501,501)
    for path in ('Library/Caches', 'Library/Preferences', 'Library/Logs'): extras['root/' + path] = (0o700,0,0)
    extras['mobile/tmp'] = (0o700,501,501)
    for path, metadata in extras.items(): directories.setdefault('/private/var/' + path, metadata)
    directories.pop('/private/var', None)
    links['/private/var/db/timezone/zoneinfo'] = '/usr/share/zoneinfo.default'
    links['/private/var/db/timezone/localtime'] = '/var/db/timezone/zoneinfo/UTC'
    result = [f'd\t{mode:o}\t{uid}\t{gid}\t{path}\n' for path,(mode,uid,gid) in sorted(directories.items())]
    result += [f'l\t{target}\t{path}\n' for path,target in sorted(links.items())]
    return ''.join(result)

def jobs(root, system, original, generated, hooks, labels=None):
    labels = DEFAULT_JOBS if labels is None else labels
    stock = {}
    for directory in ('System/Library/LaunchDaemons', 'System/Library/LaunchAngels'):
        node = original.get(directory)
        if node:
            for name, child in sorted(node.children.items()):
                if name.endswith('.plist') and stat.S_ISREG(child.mode): stock.setdefault(name[:-6], child)
    for label in labels:
        safe_relative(label)
        if label not in stock: raise ValueError('Required launch job absent: ' + label)
    for label, node in sorted(stock.items()):
        hooks.check()
        selected = label in labels
        if not selected and any(word in label for word in DENY): continue
        if Path(node.source).stat().st_size > 4 * 1024**2: raise ValueError('Launch job exceeds limit')
        with open(node.source, 'rb') as stream: job = plistlib.load(stream)
        program = job.get('Program') or (job.get('ProgramArguments') or [''])[0]
        if not isinstance(program, str) or not program.startswith('/'): raise ValueError('Invalid launch program')
        present = system.get(program.lstrip('/'))
        if not present or not stat.S_ISREG(present.mode):
            if selected: raise ValueError('Required job program missing: ' + label)
            continue
        if not selected:
            if not job.get('MachServices'): continue
            for key in ('RunAtLoad','KeepAlive','StartInterval','StartCalendarInterval','WatchPaths',
                        'QueueDirectories','StartOnMount','LaunchEvents'): job.pop(key, None)
        else: job.pop('_LimitLoadToDeviceTree', None)
        job['StandardErrorPath'] = job['StandardOutPath'] = '/dev/console'
        if isinstance(job.get('ThrottleInterval'), str) and job['ThrottleInterval'].isdigit():
            job['ThrottleInterval'] = int(job['ThrottleInterval'])
        if label == 'com.apple.backboardd': job.setdefault('EnvironmentVariables', {})['OS_ACTIVITY_DT_MODE'] = 'YES'
        generated_file(root, generated, 'LaunchDaemons/' + label + '.plist', plistlib.dumps(job, fmt=plistlib.FMT_BINARY))

def assemble_trees(extracted, resources, manifest, generated, hooks=None):
    hooks = hooks or Hooks(); generated = Path(generated); generated.mkdir(parents=True, exist_ok=True)
    root_rows, root_sources, all_rows, root_directory = extracted['root']
    original = Tree.from_manifest(root_rows, root_directory, root_sources)
    system = Tree.from_manifest(root_rows, root_directory, root_sources)
    for path in ('System/Library/LaunchDaemons','System/Library/NanoLaunchDaemons',
                 'System/Library/LaunchAngels','System/Library/xpc/launchd.plist'): system.remove(path)
    system.link('System/Library/LaunchDaemons', '/redwood/LaunchDaemons')
    for path in ('redwood','System/Volumes/iOS','System/Library/Audio/Plug-Ins/HAL',
                 'System/Library/Extensions','System/Cryptexes'): system.directory(path)
    launchd = system.get('sbin/launchd')
    if launchd is None or not stat.S_ISREG(launchd.mode): raise ValueError('Apple launchd absent')
    system.remove('sbin/launchd'); system.put('sbin/launchd.ios', launchd)
    system.file('sbin/launchd', resources['stage0'], 0o755)
    for key, mount in (('os','OS'),('app','App')):
        rows, sources, _, directory = extracted[key]
        tree = Tree.from_manifest(rows, directory, sources)
        system.put('System/Cryptexes/' + mount, tree.root)
    if system.get('System/Cryptexes/App/usr/libexec/webbookmarksd') is None:
        raise ValueError('App cryptex is incomplete')
    root = Tree(); root.file('sbin/init', resources['init'], 0o755); root.file('bin/child', resources['child'], 0o755)
    for path, name in manifest.get('root_files', {}).items():
        safe_relative(path)
        if not path.startswith(('bin/','sbin/','lib/')) or name not in resources or name in ('Image','kernel','stage0','7zz','unzbm'):
            raise ValueError('Invalid owned helper mapping')
        if name==AUDIO_CONFIG_NAME and path!=AUDIO_CONFIG_PATH:
            raise ValueError('Owned audio configuration has an invalid guest destination')
        root.file(path, resources[name], 0o644 if name==AUDIO_CONFIG_NAME else 0o755)
    if root.get(AUDIO_EXECUTABLE_PATH):
        if root.get(AUDIO_CONFIG_PATH) is None:raise ValueError('Owned audio bundle configuration absent')
        system.link('System/Library/Audio/Plug-Ins/HAL/RedwoodAudio.driver','/redwood/lib/RedwoodAudio.driver')
    for path in ('LaunchDaemons','etc','var'): root.directory(path)
    generated_file(root, generated, 'etc/rc', b'exec /sbin/launchd.ios\n')
    # CPU smoke boot needs no background benchmark or unlock gesture automation.
    generated_file(root, generated, 'etc/rc.jobs', b'# no automatic diagnostic jobs\n')
    injections = []
    for path, processes in manifest.get('injections', {}).items():
        if not path.startswith('/redwood/lib/') or root.get(path[len('/redwood/'):]) is None:
            raise ValueError('Injection library not staged')
        if not processes or any(not isinstance(name,str) or not name.replace('_','').replace('-','').isalnum() for name in processes):
            raise ValueError('Invalid injection process name')
        injections.append(path + ' ' + ' '.join(processes) + '\n')
    generated_file(root, generated, 'etc/inject.conf', ''.join(injections).encode())
    skeleton = var_skeleton(all_rows)
    # Owned startup settings are serialized only during the private install; no Apple plist bytes ship.
    preferences = {
        'com.apple.Accessibility': {'EnhancedBackgroundContrastEnabled':True, 'ReduceMotionEnabled':True},
        'com.apple.assistant.support': {'Offline Dictation Status':{}},
        'com.apple.coremedia': {'wirelessdisplay_max_count':0},
        'com.apple.frontboard': {'FBLaunchWatchdogScale':20.0},
        'com.apple.keyboard.preferences': {'DidShowContinuousPathIntroduction':True},
        'com.apple.migration': {'LastSystemVersion':'20F66','DMLastMigrationResults':{'success':True,'buildVersion':'20F66'}},
        'com.apple.purplebuddy': {'SetupDone':True,'SetupVersion':11,'SetupState':'SetupUsingAssistant','ForceNoBuddy':True},
        'com.apple.springboard': {'FBLaunchWatchdogScale':20.0,'BKNoWatchdogs':True,'SBShowBatteryPercentage':True},
        'com.apple.VideoProcessing': {'threading':'auto','max-threads':'7'}}
    for name, values in sorted(preferences.items()):
        path = 'mobile/Library/Preferences/' + name + '.plist'
        generated_file(root, generated, 'var/' + path, plistlib.dumps(values, fmt=plistlib.FMT_BINARY))
        skeleton += f'f\t644\t501\t501\t/private/var/{path}\t/var/{path}\n'
    generated_file(root, generated, 'etc/var.skel', skeleton.encode())
    jobs(root, system, original, generated, hooks, manifest.get('launch_jobs'))
    if manifest.get('persistence') is True:
        root.file('bin/var_store',resources['var_store'],0o755)
        job={'Label':'com.redwood.varstore',
             'ProgramArguments':['/redwood/bin/var_store','watch','60'],
             'RunAtLoad':True,'KeepAlive':{'SuccessfulExit':False},'ThrottleInterval':10,
             'StandardOutPath':'/dev/console','StandardErrorPath':'/dev/console'}
        generated_file(root,generated,'LaunchDaemons/com.redwood.varstore.plist',plistlib.dumps(job,fmt=plistlib.FMT_BINARY))
    return root, system
