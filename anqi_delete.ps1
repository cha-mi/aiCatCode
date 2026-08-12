param([string]$FilePath)
[IO.File]::WriteAllText([IO.Path]::Combine($env:TEMP, 'anqi_delete_path.txt'), $FilePath, [Text.Encoding]::UTF8)
Start-Process -FilePath "$PSScriptRoot\安琪.exe" -ArgumentList '--delete-file-pending'
