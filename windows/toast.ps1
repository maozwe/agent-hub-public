param([ValidateSet(8876,8892)][int]$Port=8876)
$ErrorActionPreference='Stop'
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType=WindowsRuntime] | Out-Null
$document = New-Object Windows.Data.Xml.Dom.XmlDocument
$document.LoadXml("<toast activationType='protocol' launch='http://127.0.0.1:$Port/'><visual><binding template='ToastGeneric'><text>Agent Hub</text><text>There is an update in your decision center. Open Agent Hub to view it.</text></binding></visual></toast>")
$notification = [Windows.UI.Notifications.ToastNotification]::new($document)
$notification.Tag = 'hub-update'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('AgentHub').Show($notification)
