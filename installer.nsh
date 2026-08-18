; NSIS 自定义脚本：注册/卸载 Windows 右键菜单"呼叫安琪铲除"
; 直接通过 安琪.exe "%1" 传文件路径，单实例锁的 second-instance 事件会解析 argv 中的路径
; 完全不经过 PowerShell，无黑框闪现

!macro customInstall
  ; 注册所有文件的右键菜单
  WriteRegStr HKCU "Software\Classes\*\shell\AnqiDelete" "" "呼叫安琪铲除"
  WriteRegStr HKCU "Software\Classes\*\shell\AnqiDelete" "Icon" "$INSTDIR\安琪.exe"
  WriteRegStr HKCU "Software\Classes\*\shell\AnqiDelete\command" "" '"$INSTDIR\安琪.exe" "%1"'
!macroend

!macro customUnInstall
  DeleteRegKey HKCU "Software\Classes\*\shell\AnqiDelete"
!macroend
