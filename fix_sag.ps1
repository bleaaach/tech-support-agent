Write-Host "=== SAG PostgreSQL 快速修复 ===" -ForegroundColor Cyan

# 1. 修改SAG配置使用5432端口
Write-Host "`n修改SAG配置..." -ForegroundColor Yellow
$envFile = "D:\SAG\.env"
$content = Get-Content $envFile
$original = $content -join "`n"
$content = $content -replace 'localhost:5433', 'localhost:5432'
$content | Set-Content $envFile
Write-Host "已修改为使用5432端口" -ForegroundColor Green

# 2. 创建数据库
Write-Host "`n创建SAG数据库..." -ForegroundColor Yellow
$passwords = @("", "postgres", "admin", "root", "password")
$success = $false

foreach ($pwd in $passwords) {
    Write-Host "  尝试密码: '$pwd'" -ForegroundColor Gray
    $env:PGPASSWORD = $pwd
    
    $result = & "C:\Program Files\PostgreSQL\16\bin\psql.exe" -U postgres -c "CREATE USER sag_lite WITH PASSWORD 'sag_lite_pass';" 2>&1
    if ($LASTEXITCODE -eq 0 -or $result -like "*already exists*") {
        Write-Host "  ✅ 连接成功！" -ForegroundColor Green
        
        & "C:\Program Files\PostgreSQL\16\bin\psql.exe" -U postgres -c "CREATE DATABASE sag_lite OWNER sag_lite;" 2>&1 | Out-Null
        & "C:\Program Files\PostgreSQL\16\bin\psql.exe" -U postgres -c "GRANT ALL PRIVILEGES ON DATABASE sag_lite TO sag_lite;" 2>&1 | Out-Null
        
        $success = $true
        break
    }
}

if ($success) {
    Write-Host "`n✅ 数据库创建成功！" -ForegroundColor Green
    Write-Host "`n运行数据库迁移..." -ForegroundColor Yellow
    cd D:\SAG
    npm run db:migrate
    
    Write-Host "`n=== 修复完成！===" -ForegroundColor Green
    Write-Host "`n请执行: cd D:\SAG && npm run dev" -ForegroundColor Cyan
    Write-Host "然后访问: http://localhost:5174" -ForegroundColor Cyan
} else {
    Write-Host "`n❌ 无法连接PostgreSQL" -ForegroundColor Red
}
