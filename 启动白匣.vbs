Option Explicit
Dim fso, shell, root, url, http, checkCmd, rc

Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
root = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = root
url = "http://127.0.0.1:8765"

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

checkCmd = "cmd.exe /c python -c ""import fastapi, uvicorn, multipart, PIL, fitz, docx, openpyxl, imageio_ffmpeg, cv2, numpy, onnxruntime, rapidocr_onnxruntime, pillow_heif, faster_whisper, qrcode"""
rc = shell.Run(checkCmd, 0, True)
If rc <> 0 Then
  MsgBox "BAIXIA dependencies are missing. Please run install.bat or run.bat first.", 48, "BAIXIA"
  WScript.Quit
End If

shell.Run "pythonw.exe """ & root & "\app.py""", 0, False
