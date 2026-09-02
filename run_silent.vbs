Set WshShell = CreateObject("WScript.Shell")
ScriptDir = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\"))
WshShell.CurrentDirectory = ScriptDir
WshShell.Run "pythonw.exe """ & ScriptDir & "token_counter_gui.pyw""", 0, False
Set WshShell = Nothing
