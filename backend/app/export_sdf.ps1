param(
    [Parameter(Mandatory = $true)][string]$Sdf,
    [Parameter(Mandatory = $true)][string]$Dll,
    [Parameter(Mandatory = $true)][string]$Native,
    [Parameter(Mandatory = $true)][string]$Out
)

$ErrorActionPreference = "Stop"
$work = Join-Path $env:TEMP "buchhaltung-sqlce"
New-Item -ItemType Directory -Force -Path $work | Out-Null
Copy-Item -Force $Dll (Join-Path $work "System.Data.SqlServerCe.dll")
Copy-Item -Force (Join-Path $Native "*.dll") $work
$env:PATH = "$work;" + $env:PATH
Add-Type -Path (Join-Path $work "System.Data.SqlServerCe.dll")

function Convert-Cell($value) {
    if ($null -eq $value -or $value -is [DBNull]) { return $null }
    if ($value -is [datetime]) { return $value.ToString("yyyy-MM-dd") }
    if ($value -is [bool]) { return [bool]$value }
    if ($value -is [decimal] -or $value -is [double] -or $value -is [single]) {
        return ([decimal]$value).ToString([Globalization.CultureInfo]::InvariantCulture)
    }
    if ($value -is [byte]) {
        return [int]$value
    }
    return $value
}

function Convert-Row($row) {
    $obj = [ordered]@{}
    foreach ($column in $row.Table.Columns) {
        $obj[$column.ColumnName] = Convert-Cell $row[$column]
    }
    return $obj
}

$conn = New-Object System.Data.SqlServerCe.SqlCeConnection ("Data Source=" + $Sdf)
$conn.Open()
$utf8 = New-Object System.Text.UTF8Encoding $false
$writer = New-Object System.IO.StreamWriter($Out, $false, $utf8)
try {
    $tables = @(
        @{ Name = "kunden"; Sql = "SELECT * FROM Kundes" },
        @{ Name = "rechnungen"; Sql = "SELECT * FROM Rechnungs" },
        @{ Name = "positionen"; Sql = "SELECT * FROM Positions" },
        @{ Name = "serienpositionen"; Sql = "SELECT * FROM Serienpositionens" },
        @{ Name = "optionen"; Sql = "SELECT * FROM Options" }
    )
    foreach ($table in $tables) {
        $adapter = New-Object System.Data.SqlServerCe.SqlCeDataAdapter($table.Sql, $conn)
        $data = New-Object System.Data.DataTable
        [void]$adapter.Fill($data)
        foreach ($row in $data.Rows) {
            $payload = @{ table = $table.Name; row = (Convert-Row $row) }
            $writer.WriteLine(($payload | ConvertTo-Json -Compress -Depth 6))
        }
        Write-Output ("{0}={1}" -f $table.Name, $data.Rows.Count)
    }
}
finally {
    $writer.Close()
    $conn.Close()
}
