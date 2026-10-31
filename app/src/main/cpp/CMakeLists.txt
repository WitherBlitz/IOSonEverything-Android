# The AVF display/camera helpers. This derivative packages the retained binary;
# rebuild separately with native/build-scfb.py or the CMake command in the build guide.
cmake_minimum_required(VERSION 3.22)
project(scfb C)
add_library(scfb SHARED scfb_present.c sccam_put.c)
target_compile_options(scfb PRIVATE -O2 -Wall -Wextra -Werror)
target_link_options(scfb PRIVATE -Wl,-z,max-page-size=16384)
target_link_libraries(scfb android log)
