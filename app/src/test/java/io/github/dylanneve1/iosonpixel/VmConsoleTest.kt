package io.github.dylanneve1.iosonpixel

import java.io.ByteArrayInputStream
import java.io.File
import java.io.IOException
import java.io.OutputStream
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

class VmConsoleTest {
    @get:Rule val temporary = TemporaryFolder()

    @Test fun failedLogWriteStillDrainsTheEntireConsole() {
        val input = ByteArrayInputStream("first\nsecond\nlast\n".toByteArray())
        val lines = mutableListOf<String>()
        VmConsole(temporary.newFile(), open = { object : OutputStream() {
            override fun write(value: Int) { throw IOException("disk full") }
        } }).drain(input, lines::add)
        assertEquals(0, input.available())
        assertTrue(lines.containsAll(listOf("first", "second", "last")))
        assertEquals(1, lines.count { it.startsWith("warning:") })
    }

    @Test fun repeatedOutputRotatesWithinTwoFileBudget() {
        val file = temporary.newFile("qemu.log")
        val lines = (1..50).map { "line-$it-abcdefghij" }
        VmConsole(file, maxBytes = 128, maxLine = 24).drain(ByteArrayInputStream(lines.joinToString("\n").toByteArray())) {}
        val previous = File(file.path + ".previous")
        assertTrue(previous.isFile)
        assertTrue(file.length() <= 128)
        assertTrue(previous.length() <= 128)
        assertTrue(file.readText().contains(lines.last()))
    }

    @Test fun oversizedUnterminatedLineIsBoundedButFollowingLinesSurvive() {
        val file = temporary.newFile()
        val lines = mutableListOf<String>()
        VmConsole(file, maxBytes = 256, maxLine = 32).drain(
            ByteArrayInputStream(("x".repeat(100000) + "\nafter\n").toByteArray()), lines::add)
        assertTrue(lines.first().length <= 64)
        assertTrue(lines.first().contains("truncated"))
        assertEquals("after", lines.last())
        assertTrue(file.length() <= 256)
    }

    @Test fun observerFailureDoesNotInterruptDraining() {
        val input = ByteArrayInputStream("one\ntwo\nthree\n".toByteArray())
        var calls = 0
        VmConsole(temporary.newFile()).drain(input) { calls++; throw IllegalStateException("observer") }
        assertEquals(3, calls)
        assertEquals(0, input.available())
    }
}
