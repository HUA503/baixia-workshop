Option Explicit
Dim fso, shell, root, pidFile, pid, wmi, procs, proc, commandLine

Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
root = fso.GetParentFolderName(WScript.ScriptFullName)
pidFile = root & "\.baixia.pid"

If Not fso.FileExists(pidFile) Then
  WScript.Quit
End If

On Error Resume Next
pid = Trim(fso.OpenTextFile(pidFile, 1).ReadAll)
If Len(pid) > 0 Then
  Set wmi = GetObject("winmgmts:\\.\root\cimv2")
  Set procs = wmi.ExecQuery("SELECT ProcessId, CommandLine FROM Win32_Process WHERE ProcessId=" & pid)
  For Each proc In procs
    commandLine = LCase(proc.CommandLine)
    If InStr(commandLine, "app.py") > 0 Then
      shell.Run "taskkill /PID " & pid & " /F", 0, True
    End If
  Next
End If
fso.DeleteFile pidFile, True
On Error GoTo 0
