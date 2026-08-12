; NSIS 自定义脚本：注册/卸载 Windows 右键菜单"呼叫安琪铲除"

!macro customInstall
  ; 注册所有文件的右键菜单
  ; 使用 PowerShell 脚本中转：把文件路径写入临时文件（UTF-8），避免命令行中文乱码
  WriteRegStr HKCU "Software\Classes\*\shell\AnqiDelete" "" "呼叫安琪铲除"
  WriteRegStr HKCU "Software\Classes\*\shell\AnqiDelete" "Icon" "$INSTDIR\安琪.exe"
  WriteRegStr HKCU "Software\Classes\*\shell\AnqiDelete\command" "" 'powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "$INSTDIR\anqi_delete.ps1" -FilePath "%1"'
!macroend

!macro customUnInstall
  DeleteRegKey HKCU "Software\Classes\*\shell\AnqiDelete"
!macroend
