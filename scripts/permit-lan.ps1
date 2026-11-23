#Requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'

# Instale antes de publicar a porta LAN. Nao altera regras do Docker Desktop.
$localIp = '192.168.0.121'
$lan = '192.168.0.0/24'
$interface = 'Ethernet'
$ip = Get-NetIPAddress -AddressFamily IPv4 -IPAddress $localIp -InterfaceAlias $interface
if ($ip.PrefixLength -ne 24 -or $ip.AddressState -ne 'Preferred') {
    throw 'O IPv4 ativo da Ethernet nao corresponde a configuracao LAN do Cassino.'
}
$category = (Get-NetConnectionProfile -InterfaceAlias $interface).NetworkCategory
$profile = if ($category -eq 'DomainAuthenticated') { 'Domain' } else { [string]$category }
$policy = Get-NetFirewallProfile -PolicyStore ActiveStore -Name $profile
if ($policy.Enabled -ne 'True' -or $policy.AllowLocalFirewallRules -eq 'False') {
    throw 'O perfil ativo precisa de firewall ligado e regras locais aplicaveis.'
}
if (Get-NetIPInterface -AddressFamily IPv4 | Where-Object WeakHostReceive -eq 'Enabled') {
    throw 'Recebimento IPv4 WeakHost ativo; revise a interface antes de publicar.'
}

$scope = @{ Direction = 'Inbound'; Protocol = 'TCP'; LocalPort = 3000; LocalAddress = $localIp; Profile = 'Any'; PolicyStore = 'PersistentStore' }
$block = 'Cassino-LAN-3000-BlockOutside'
$allow = 'Cassino-LAN-3000-AllowLocal'
# Um bloqueio explicito vence a permissao ampla do Docker Desktop. Intervalos complementares da /24.
if (-not (Get-NetFirewallRule -Name $block -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule @scope -Name $block -DisplayName 'Cassino LAN TCP 3000 - bloquear fora da sub-rede' -Action Block -RemoteAddress '0.0.0.0-192.168.0.0','192.168.0.255-255.255.255.255' | Out-Null
}
if (-not (Get-NetFirewallRule -Name $allow -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule @scope -Name $allow -DisplayName 'Cassino LAN TCP 3000 - permitir sub-rede local' -Action Allow -RemoteAddress $lan -InterfaceAlias $interface -EdgeTraversalPolicy Block | Out-Null
}
Get-NetFirewallRule -PolicyStore ActiveStore -Name $block,$allow | Format-Table Name,Enabled,Action,Profile
