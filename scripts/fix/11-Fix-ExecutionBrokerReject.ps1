#Requires -Version 7.0
[CmdletBinding()]
param([string]$ProjectRoot = (Resolve-Path "$PSScriptRoot\..\..").Path)

$ErrorActionPreference = 'Stop'
$file = Join-Path $ProjectRoot 'fxars\execution\service.py'
Write-Host "[FIX-11] Execution broker reject/unknown" -ForegroundColor Cyan

$content = Get-Content $file -Raw -Encoding UTF8
if ($content -match 'FIX-11-BROKER-STATUS') {
    Write-Host "  Already patched. Skipping." -ForegroundColor Yellow
    return
}

$old = @'
        intent = transition(intent, OrderStatus.SUBMITTED)
        broker_order, fills = self.broker.submit(intent, price=price, pip_size=pip_size)
        target = OrderStatus.FILLED if broker_order.status is OrderStatus.FILLED else OrderStatus.PARTIALLY_FILLED
        intent = transition(intent, OrderStatus.ACKNOWLEDGED)
        intent = transition(intent, target)
        with self.orders.db.transaction():
            self.orders.save_intent(intent)
            self.orders.save_broker_order(broker_order)
            for fill in fills:
                self.orders.save_fill(fill)
            self.audit.append(
                "ORDER_SUBMITTED", "order_intent", intent.intent_id, actor=actor,
                payload={"broker_order_id": broker_order.broker_order_id, "status": target.value},
            )
        return intent
'@
$new = @'
        intent = transition(intent, OrderStatus.SUBMITTED)
        broker_order, fills = self.broker.submit(intent, price=price, pip_size=pip_size)

        # FIX-11-BROKER-STATUS: نگاشت صحیح وضعیت بروکر
        broker_status = broker_order.status
        if broker_status is OrderStatus.REJECTED:
            intent = transition(intent, OrderStatus.REJECTED)
            with self.orders.db.transaction():
                self.orders.save_intent(intent)
                self.orders.save_broker_order(broker_order)
                self.audit.append(
                    "ORDER_REJECTED", "order_intent", intent.intent_id, actor=actor,
                    payload={"broker_order_id": broker_order.broker_order_id,
                             "message": broker_order.message},
                )
            return intent

        if broker_status is OrderStatus.UNKNOWN:
            intent = transition(intent, OrderStatus.UNKNOWN)
            with self.orders.db.transaction():
                self.orders.save_intent(intent)
                self.orders.save_broker_order(broker_order)
                self.audit.append(
                    "ORDER_UNKNOWN", "order_intent", intent.intent_id, actor=actor,
                    payload={"broker_order_id": broker_order.broker_order_id,
                             "message": broker_order.message},
                )
            return intent

        if broker_status is OrderStatus.CANCELED:
            intent = transition(intent, OrderStatus.ACKNOWLEDGED)
            intent = transition(intent, OrderStatus.CANCELED)
            with self.orders.db.transaction():
                self.orders.save_intent(intent)
                self.orders.save_broker_order(broker_order)
                self.audit.append(
                    "ORDER_CANCELED", "order_intent", intent.intent_id, actor=actor,
                    payload={"broker_order_id": broker_order.broker_order_id},
                )
            return intent

        target = (OrderStatus.FILLED if broker_status is OrderStatus.FILLED
                  else OrderStatus.PARTIALLY_FILLED if broker_status is OrderStatus.PARTIALLY_FILLED
                  else OrderStatus.ACKNOWLEDGED)
        intent = transition(intent, OrderStatus.ACKNOWLEDGED)
        if target is not OrderStatus.ACKNOWLEDGED:
            intent = transition(intent, target)
        with self.orders.db.transaction():
            self.orders.save_intent(intent)
            self.orders.save_broker_order(broker_order)
            for fill in fills:
                self.orders.save_fill(fill)
            self.audit.append(
                "ORDER_SUBMITTED", "order_intent", intent.intent_id, actor=actor,
                payload={"broker_order_id": broker_order.broker_order_id, "status": target.value},
            )
        return intent
'@
if (-not $content.Contains($old)) { throw "submit anchor not found" }
$content = $content.Replace($old, $new)
$content = $content + "`r`n# FIX-11-BROKER-STATUS`r`n"
Set-Content -Path $file -Value $content -Encoding UTF8 -NoNewline
Write-Host "  [OK] execution service patched" -ForegroundColor Green