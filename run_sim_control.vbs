' run_sim_control.vbs — avvio silenzioso (senza finestra nera)
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run """" & "C:\SplKnetx\knetxenv313\Scripts\pythonw.exe" & """" & " " & """" & "C:\SplKnetx\runtime\localsim\knetx_sim_control.py" & """", 0, False
