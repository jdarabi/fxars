#Requires -Version 7.0
[CmdletBinding()]
param([string]$ProjectRoot = (Resolve-Path "$PSScriptRoot\..\..").Path)

$ErrorActionPreference = 'Stop'
Write-Host "[FIX-10] Identity sessions" -ForegroundColor Cyan

# 10.1 افزودن revoke_all به SessionRepository
$repoFile = Join-Path $ProjectRoot 'fxars\storage\repositories.py'
$content = Get-Content $repoFile -Raw -Encoding UTF8
if ($content -notmatch 'def revoke_all') {
    $old = @'
    def revoke(self, token_hash: str) -> None:
        self.db.execute("UPDATE sessions SET revoked=1 WHERE token_hash=?", (token_hash,))
'@
    $new = @'
    def revoke(self, token_hash: str) -> None:
        self.db.execute("UPDATE sessions SET revoked=1 WHERE token_hash=?", (token_hash,))

    # FIX-10-REVOKE-ALL
    def revoke_all(self, user_id: str) -> int:
        cur = self.db.execute("UPDATE sessions SET revoked=1 WHERE user_id=? AND revoked=0", (user_id,))
        return cur.rowcount
'@
    if (-not $content.Contains($old)) { throw "SessionRepository.revoke anchor not found" }
    $content = $content.Replace($old, $new)
    Set-Content -Path $repoFile -Value $content -Encoding UTF8 -NoNewline
    Write-Host "  [OK] SessionRepository.revoke_all added" -ForegroundColor Green
}

# 10.2 اصلاح IdentityService.set_password و create_user
$file = Join-Path $ProjectRoot 'fxars\identity\service.py'
$content = Get-Content $file -Raw -Encoding UTF8
if ($content -match 'FIX-10-IDENTITY') {
    Write-Host "  IdentityService already patched" -ForegroundColor Yellow
    return
}

$oldSetPass = @'
    def set_password(self, user_id: str, password: str, *, actor: str) -> None:
        user = self.users.get(user_id)
        if user is None:
            raise ValidationError("کاربر یافت نشد.")
        encoded = hash_password(password, iterations=self.settings.security.pbkdf2_iterations)
        from dataclasses import replace

        self.users.save(replace(user, password_hash=encoded))
        self.sessions.revoke_all(user_id) if hasattr(self.sessions, "revoke_all") else None
        self.audit.append("USER_PASSWORD_CHANGED", "user", user_id, actor=actor, payload={})
'@
$newSetPass = @'
    def set_password(self, user_id: str, password: str, *, actor: str) -> None:
        """FIX-10-IDENTITY: تغییر رمز + ابطال همه نشست‌ها در یک تراکنش."""
        user = self.users.get(user_id)
        if user is None:
            raise ValidationError("کاربر یافت نشد.")
        encoded = hash_password(password, iterations=self.settings.security.pbkdf2_iterations)
        from dataclasses import replace

        with self.users.db.transaction():
            self.users.save(replace(user, password_hash=encoded))
            revoked = self.sessions.revoke_all(user_id)
            self.audit.append(
                "USER_PASSWORD_CHANGED", "user", user_id, actor=actor,
                payload={"revoked_sessions": revoked},
            )
'@
if (-not $content.Contains($oldSetPass)) { throw "set_password anchor not found" }
$content = $content.Replace($oldSetPass, $newSetPass)

# create_user: اجبار MFA برای نقش‌های MFAاجباری
$oldCreate = @'
        role = Role(role)
        if self.users.get_by_username(username) is not None:
            raise ValidationError(f"نام کاربری {username} قبلاً ثبت شده است.")
'@
$newCreate = @'
        role = Role(role)
        if self.users.get_by_username(username) is not None:
            raise ValidationError(f"نام کاربری {username} قبلاً ثبت شده است.")
        # FIX-10-IDENTITY: نقش‌های MFAاجباری باید از ابتدا TOTP داشته باشند
        if role in self.settings.security.mfa_roles and not totp_enabled:
            raise ValidationError(
                f"نقش {role.value} نیازمند MFA است؛ ساخت کاربر بدون TOTP مجاز نیست.",
                details={"role": role.value, "mfa_roles": [r.value for r in self.settings.security.mfa_roles]},
            )
'@
if (-not $content.Contains($oldCreate)) { throw "create_user anchor not found" }
$content = $content.Replace($oldCreate, $newCreate)

$content = $content + "`r`n# FIX-10-IDENTITY`r`n"
Set-Content -Path $file -Value $content -Encoding UTF8 -NoNewline
Write-Host "  [OK] IdentityService patched" -ForegroundColor Green