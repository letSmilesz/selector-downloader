' run_gui.vbs - silent GUI entry: runs run_gui.bat --silent in a hidden window.
Set fso = CreateObject("Scripting.FileSystemObject")
bat = fso.GetParentFolderName(WScript.ScriptFullName) & "\run_gui.bat"
CreateObject("Wscript.Shell").Run "cmd /c """ & bat & """ --silent", 0, False