Option Explicit
Dim fso, shell, root, url, apiUrl, http, checkCmd, rc, i

Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
root = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = root
url = "http://127.0.0.1:8765"
apiUrl = url & "/api/network"

On Error Resume Next
Set http = CreateObject("MSXML2.ServerXMLHTTP.6.0")
http.setTimeouts 500, 500, 500, 500
http.open "GET", apiUrl, False
http.send
If Err.Number = 0 Then
  If http.status = 200 Then
    If InStr(LCase(http.responseText), """lan_enabled"":true") > 0 Then
      shell.Run url, 1, False
      WScript.Quit
    Else
      MsgBox "BAIXIA is already running in local-only mode." & vbCrLf & vbCrLf & "Stop it with the stop script, then launch LAN mode again.", 48, "BAIXIA LAN"
      WScript.Quit
    End If
  End If
End If
Err.Clear
On Error GoTo 0

checkCmd = "cmd.exe /c python -c ""import fastapi, uvicorn, multipart, PIL, fitz, docx, openpyxl, imageio_ffmpeg, cv2, numpy, onnxruntime, rapidocr_onnxruntime, pillow_heif, faster_whisper, qrcode"""
rc = shell.Run(checkCmd, 0, True)
If rc <> 0 Then
  MsgBox "BAIXIA dependencies are missing. Please run install.bat first.", 48, "BAIXIA LAN"
  WScript.Quit
End If

shell.Environment("PROCESS")("BAIXIA_HOST") = "0.0.0.0"
shell.Environment("PROCESS")("BAIXIA_PORT") = "8765"
shell.Environment("PROCESS")("BAIXIA_NO_BROWSER") = "1"
shell.Run "pythonw.exe """ & root & "\app.py""", 0, False

For i = 1 To 40
  WScript.Sleep 500
  On Error Resume Next
  Set http = CreateObject("MSXML2.ServerXMLHTTP.6.0")
  http.setTimeouts 400, 400, 400, 400
  http.open "GET", url & "/api/health", False
  http.send
  If Err.Number = 0 Then
    If http.status = 200 Then
      shell.Run url, 1, False
      WScript.Quit
    End If
  End If
  Err.Clear
  On Error GoTo 0
Next

MsgBox "BAIXIA LAN mode did not start. Check firewall or port 8765.", 48, "BAIXIA LAN"
