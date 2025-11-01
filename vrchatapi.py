"""
VRChat API client
"""

from __future__ import annotations

import os
import time
from collections import deque
import logging
from typing import Any, Dict, List, Optional

import requests


try:
    import pyotp  
    _PYOTP_AVAILABLE = True
except Exception:
    _PYOTP_AVAILABLE = False

try:
    import yaml  
    _YAML_AVAILABLE = True
except Exception:
    _YAML_AVAILABLE = False


logger = logging.getLogger(__name__)


class VRChatAPIError(Exception):
    pass




_LAST_2FA_400_TS: float = 0.0
_TWOFA_BACKOFF_SECONDS: float = 120.0








_REQ_TIMES = deque()  
_LAST_REQ_TS: float = 0.0
_BACKOFF_UNTIL_TS: float = 0.0

def _get_rate_params():
    try:
        min_interval = float(os.environ.get("VRCHAT_RATE_MIN_INTERVAL_SECONDS", "3.0") or 3.0)
    except ValueError:
        min_interval = 3.0
    try:
        max_per_minute = int(os.environ.get("VRCHAT_RATE_MAX_PER_MINUTE", "20") or 20)
    except ValueError:
        max_per_minute = 20
    try:
        backoff_default = float(os.environ.get("VRCHAT_RATE_BACKOFF_SECONDS", "60") or 60)
    except ValueError:
        backoff_default = 60.0
    return min_interval, max_per_minute, backoff_default

def _purge_old_requests(now: float):
    
    cutoff = now - 60.0
    while _REQ_TIMES and _REQ_TIMES[0] < cutoff:
        _REQ_TIMES.popleft()


class VRChatAPI:
    BASE_URL = "https://api.vrchat.cloud/api/1"

    def __init__(
        self,
        app_name: str,
        app_version: str,
        app_contact: str,
        timeout: float = 15.0,
        session: Optional[requests.Session] = None,
    ):
        self.session = session or requests.Session()
        self.timeout = timeout

        
        self.session.headers.update(
            {
                "User-Agent": f"{app_name}/{app_version} ({app_contact})",
                "Accept": "application/json",
            }
        )

        
        self._username: Optional[str] = None
        self._password: Optional[str] = None

    
    
    
    def _limited_request(self, method: str, url: str, *, timeout: Optional[float] = None, auth=None, **kwargs):
        """Perform an HTTP request with global rate limiting and backoff.

        - Enforces minimum interval between requests
        - Enforces max per-minute window
        - Applies backoff if a prior 429/503 was received
        - Honors Retry-After header if present
        """
        global _LAST_REQ_TS, _REQ_TIMES, _BACKOFF_UNTIL_TS
        min_interval, max_per_minute, backoff_default = _get_rate_params()

        if timeout is None:
            timeout = self.timeout

        
        now = time.time()
        if _BACKOFF_UNTIL_TS and now < _BACKOFF_UNTIL_TS:
            wait = _BACKOFF_UNTIL_TS - now
            time.sleep(min(wait, 2.0))  

        
        now = time.time()
        if _LAST_REQ_TS:
            delta = now - _LAST_REQ_TS
            if delta < min_interval:
                time.sleep(min_interval - delta)

        
        now = time.time()
        _purge_old_requests(now)
        if len(_REQ_TIMES) >= max_per_minute:
            
            to_wait = max(0.0, 60.0 - (now - _REQ_TIMES[0]))
            
            time.sleep(min(to_wait, 2.5))
            now = time.time()
            _purge_old_requests(now)

        
        try:
            r = self.session.request(method, url, timeout=timeout, auth=auth, **kwargs)
        except requests.RequestException as e:
            
            _LAST_REQ_TS = time.time()
            _REQ_TIMES.append(_LAST_REQ_TS)
            raise

        
        _LAST_REQ_TS = time.time()
        _REQ_TIMES.append(_LAST_REQ_TS)

        
        if r.status_code in (429, 503):
            retry_after = r.headers.get("Retry-After")
            secs = None
            if retry_after:
                try:
                    secs = float(retry_after)
                except ValueError:
                    secs = None
            if secs is None:
                secs = backoff_default
            _BACKOFF_UNTIL_TS = time.time() + max(1.0, secs)
        else:
            
            if r.status_code < 400:
                _BACKOFF_UNTIL_TS = 0.0

        return r

    
    
    
    def login(
        self,
        username: str,
        password: str,
        two_factor_code: Optional[str] = None,
        totp_secret: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Login to VRChat. If 2FA is required, verify using provided code or generated TOTP.
        Returns the current user object when authenticated.
        """
        self._username = username
        self._password = password

        self.session.auth = requests.auth.HTTPBasicAuth(username, password)

        
        me = self.get_current_user(throw_on_error=False)
        if me.get("ok") is True and not me.get("requiresTwoFactorAuth"):
            return me

        
        if me.get("requiresTwoFactorAuth"):
            logger.info("VRChat login requires 2FA; attempting verification")
            code_to_use = None
            if two_factor_code:
                code_to_use = two_factor_code
            elif totp_secret:
                if not _PYOTP_AVAILABLE:
                    raise VRChatAPIError(
                        "pyotp is not installed; cannot generate TOTP from secret. "
                        "Provide two_factor_code directly or install pyotp."
                    )
                try:
                    
                    
                    step = int(os.environ.get("VRCHAT_TOTP_STEP_SECONDS", "30") or 30)
                    fudge = int(os.environ.get("VRCHAT_TOTP_EDGE_FUDGE_SECONDS", "3") or 3)
                    if step <= 0:
                        step = 30
                    
                    if fudge < 0:
                        fudge = 0
                    if fudge > step // 2:
                        fudge = max(1, step // 4)

                    now_ts = int(time.time())
                    remainder = now_ts % step
                    t = pyotp.TOTP(totp_secret, interval=step)
                    
                    if remainder < fudge:
                        for_time = now_ts - step
                        edge_choice = "previous"
                    elif remainder > (step - fudge):
                        for_time = now_ts + step
                        edge_choice = "next"
                    else:
                        for_time = now_ts
                        edge_choice = "current"
                    code_to_use = t.at(for_time)
                    try:
                        logger.debug(
                            "Generated TOTP code using %s window (step=%ss, fudge=%ss, remainder=%ss)",
                            edge_choice,
                            step,
                            fudge,
                            remainder,
                        )
                    except Exception:
                        pass
                except Exception as e:
                    raise VRChatAPIError(f"Failed generating TOTP code: {e}")
            else:
                raise VRChatAPIError(
                    "2FA required but neither two_factor_code nor totp_secret was provided"
                )

            verify = self.verify_2fa(code_to_use)
            if not verify.get("verified"):
                raise VRChatAPIError("2FA verification failed")

            
            me = self.get_current_user(throw_on_error=True)
            
            try:
                self.session.auth = None
            except Exception:
                pass
            return me

        
        me = self.get_current_user(throw_on_error=True)
        
        try:
            self.session.auth = None
        except Exception:
            pass
        return me

    def verify_2fa(self, code: str) -> Dict[str, Any]:
        url = f"{self.BASE_URL}/auth/twofactorauth/totp/verify"
        try:
            r = self._limited_request("POST", url, json={"code": code}, auth=None)
            if r.status_code == 200:
                return r.json()
            
            if r.status_code == 400:
                try:
                    global _LAST_2FA_400_TS
                    _LAST_2FA_400_TS = time.time()
                except Exception:
                    pass
            raise VRChatAPIError(f"2FA verify failed: {r.status_code} {r.text}")
        except requests.RequestException as e:
            raise VRChatAPIError(f"2FA verify request error: {e}")

    def get_current_user(self, throw_on_error: bool = True) -> Dict[str, Any]:
        url = f"{self.BASE_URL}/auth/user"
        try:
            r = self._limited_request("GET", url, auth=self.session.auth)
            if r.status_code == 200:
                data = r.json()
                data.setdefault("ok", True)
                return data
            if throw_on_error:
                raise VRChatAPIError(f"get_current_user failed: {r.status_code} {r.text}")
            return {"ok": False, "status": r.status_code, "text": r.text}
        except requests.RequestException as e:
            if throw_on_error:
                raise VRChatAPIError(f"get_current_user request error: {e}")
            return {"ok": False, "error": str(e)}

    
    
    
    def list_notifications(
        self, *, hidden: Optional[bool] = None, n: int = 60, offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Retrieve notifications. Filter friend requests at call site."""
        url = f"{self.BASE_URL}/auth/user/notifications"
        params: Dict[str, Any] = {"n": max(1, min(n, 100)), "offset": max(0, offset)}
        
        if hidden is not None:
            params["hidden"] = bool(hidden)
        try:
            
            r = self._limited_request("GET", url, params=params, auth=None)
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list):
                    return data
                
                return data.get("data", []) if isinstance(data, dict) else []
            raise VRChatAPIError(f"list_notifications failed: {r.status_code} {r.text}")
        except requests.RequestException as e:
            raise VRChatAPIError(f"list_notifications request error: {e}")

    def list_friend_requests(self, *, include_hidden: bool = False, n: int = 60) -> List[Dict[str, Any]]:
        notes = self.list_notifications(hidden=include_hidden, n=n)
        return [n for n in notes if n.get("type") == "friendRequest"]

    def accept_friend_request(self, notification_id: str) -> Dict[str, Any]:
        url = f"{self.BASE_URL}/auth/user/notifications/{notification_id}/accept"
        try:
            
            r = self._limited_request("PUT", url, auth=None)
            if r.status_code == 200:
                try:
                    return {"success": True, **r.json()}
                except Exception:
                    return {"success": True, "status_code": 200}
            if r.status_code == 404:
                return {"success": False, "status_code": 404, "message": "Notification not found"}
            return {"success": False, "status_code": r.status_code, "message": r.text}
        except requests.RequestException as e:
            return {"success": False, "error": str(e)}

    def deny_friend_request(self, notification_id: str) -> Dict[str, Any]:
        """
        Hide the friend request notification (deny). For incoming requests, use hide notification.
        """
        url = f"{self.BASE_URL}/auth/user/notifications/{notification_id}/hide"
        try:
            
            r = self._limited_request("PUT", url, auth=None)
            if r.status_code == 200:
                try:
                    return {"success": True, **r.json()}
                except Exception:
                    return {"success": True, "status_code": 200}
            if r.status_code == 404:
                return {"success": False, "status_code": 404, "message": "Notification not found"}
            return {"success": False, "status_code": r.status_code, "message": r.text}
        except requests.RequestException as e:
            return {"success": False, "error": str(e)}

    
    
    
    def get_own_avatar(self) -> Dict[str, Any]:
        """Get the currently equipped avatar for the logged-in user.

        This calls GET /users/{userId}/avatar using the authenticated session cookie.
        Returns the avatar object on success, raises VRChatAPIError on failure.
        """
        
        me = self.get_current_user(throw_on_error=True)
        user_id = me.get("id") or me.get("userId")
        if not user_id:
            raise VRChatAPIError("Authenticated user id not found")

        url = f"{self.BASE_URL}/users/{user_id}/avatar"
        try:
            
            r = self._limited_request("GET", url, auth=None)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (401, 403):
                raise VRChatAPIError(f"get_own_avatar unauthorized: {r.status_code}")
            raise VRChatAPIError(f"get_own_avatar failed: {r.status_code} {r.text}")
        except requests.RequestException as e:
            raise VRChatAPIError(f"get_own_avatar request error: {e}")

    def select_avatar(self, avatar_id: str) -> Dict[str, Any]:
        """Switch to a specific avatar by id.

        This calls PUT /avatars/{avatarId}/select and returns the updated user object on success.
        """
        if not avatar_id:
            raise VRChatAPIError("avatar_id is required")
        url = f"{self.BASE_URL}/avatars/{avatar_id}/select"
        try:
            
            r = self._limited_request("PUT", url, auth=None)
            if r.status_code == 200:
                try:
                    data = r.json()
                except Exception:
                    data = {"status_code": 200}
                
                if isinstance(data, dict):
                    data.setdefault("success", True)
                return data
            if r.status_code == 404:
                return {"success": False, "status_code": 404, "message": "Avatar not found"}
            if r.status_code in (401, 403):
                return {"success": False, "status_code": r.status_code, "message": "Unauthorized"}
            return {"success": False, "status_code": r.status_code, "message": r.text}
        except requests.RequestException as e:
            return {"success": False, "error": str(e)}


def _load_vrchat_config(config_path: str = "config.yml") -> Dict[str, Any]:
    cfg: Dict[str, Any] = {}
    if _YAML_AVAILABLE and os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning(f"Failed to read {config_path}: {e}")
    return cfg.get("vrchat", {}) if isinstance(cfg, dict) else {}


def build_client_from_env_or_config(config_path: str = "config.yml") -> Dict[str, Any]:
    """
    Helper to create an authenticated VRChatAPI client using env vars or config.yml.

    Env vars (preferred):
      VRC_USERNAME, VRC_PASSWORD, VRC_TOTP_SECRET (optional), VRC_2FA_CODE (optional single-use)
      VRCHAT_APP_NAME, VRCHAT_APP_VERSION, VRCHAT_APP_CONTACT
    Config fallback (config.yml -> vrchat):
      application: name, version, contact
      credentials: username, password, two_factor_code (optional), totp_secret (optional)
    """
    vcfg = _load_vrchat_config(config_path)

    
    global _LAST_2FA_400_TS, _TWOFA_BACKOFF_SECONDS
    
    env_backoff = os.environ.get("VRCHAT_2FA_BACKOFF_SECONDS")
    if env_backoff:
        try:
            _TWOFA_BACKOFF_SECONDS = float(env_backoff)
        except ValueError:
            pass
    now = time.time()
    if _LAST_2FA_400_TS and (now - _LAST_2FA_400_TS) < _TWOFA_BACKOFF_SECONDS:
        wait = int(_TWOFA_BACKOFF_SECONDS - (now - _LAST_2FA_400_TS))
        return {
            "success": False,
            "message": f"Recent 2FA verification failed. Please wait {wait}s before trying again or provide a valid 2FA code.",
        }

    app_name = os.environ.get("VRCHAT_APP_NAME", vcfg.get("application", {}).get("name", "ProjectGabriel"))
    app_version = os.environ.get("VRCHAT_APP_VERSION", vcfg.get("application", {}).get("version", "1.0.0"))
    app_contact = os.environ.get("VRCHAT_APP_CONTACT", vcfg.get("application", {}).get("contact", "support@example.com"))

    username = os.environ.get("VRC_USERNAME", vcfg.get("credentials", {}).get("username", ""))
    password = os.environ.get("VRC_PASSWORD", vcfg.get("credentials", {}).get("password", ""))
    two_factor_code = os.environ.get("VRC_2FA_CODE", vcfg.get("credentials", {}).get("two_factor_code", "")) or None
    totp_secret = os.environ.get("VRC_TOTP_SECRET", vcfg.get("credentials", {}).get("totp_secret", "")) or None

    if not username or not password:
        return {
            "success": False,
            "message": "VRChat credentials missing. Set VRC_USERNAME and VRC_PASSWORD, or configure vrchat.credentials in config.yml",
        }

    client = VRChatAPI(app_name=app_name, app_version=app_version, app_contact=app_contact)

    try:
        me = client.login(username=username, password=password, two_factor_code=two_factor_code, totp_secret=totp_secret)
        return {"success": True, "client": client, "user": me}
    except Exception as e:
        return {"success": False, "message": str(e)}
