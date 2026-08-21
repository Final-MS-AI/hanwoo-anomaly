const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ||
  "https://hanwoo.koreacentral.cloudapp.azure.com";

// OAuth Client ID is not a secret. The fallback keeps Google login available
// when a static deployment was built without VITE_GOOGLE_CLIENT_ID.
export const GOOGLE_CLIENT_ID =
  import.meta.env.VITE_GOOGLE_CLIENT_ID ??
  "303459689220-bkuu4frgrdkil3mcp8632th1j105kkv5.apps.googleusercontent.com";

export function hasAndroidAuthBridge() {
  return (
    typeof window !== "undefined" &&
    typeof window.COWOW_ANDROID?.googleLogin === "function"
  );
}

function normalizePictureUrl(value) {
  if (typeof value !== "string" || !value) {
    return null;
  }

  try {
    const url = new URL(value);

    if (
      url.protocol === "http:" &&
      (url.hostname === "kakaocdn.net" ||
        url.hostname.endsWith(".kakaocdn.net"))
    ) {
      url.protocol = "https:";
    }

    return url.toString();
  } catch {
    return value;
  }
}

function normalizeUser(payload) {
  const source = payload?.user ?? payload;

  if (!source || typeof source !== "object") {
    throw new Error("사용자 정보가 올바르지 않습니다.");
  }

  return {
    id: source.id ?? null,
    loginType:
      source.loginType ?? source.provider ?? "unknown",
    providerUserId:
      source.providerUserId ??
      source.provider_user_id ??
      null,
    name: source.name ?? "사용자",
    email: source.email ?? "이메일 정보 없음",
    picture: normalizePictureUrl(
      source.picture ?? source.profile_image_url,
    ),
  };
}

async function parseResponse(response) {
  const contentType = response.headers.get("content-type") ?? "";
  const payload = contentType.includes("application/json")
    ? await response.json()
    : null;

  if (!response.ok) {
    throw new Error(
      payload?.detail ??
        payload?.message ??
        "요청을 처리하지 못했습니다.",
    );
  }

  return payload;
}

export async function exchangeGoogleCredential(credential) {
  const response = await fetch(`${API_BASE_URL}/auth/google`, {
    method: "POST",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ credential }),
  });

  return normalizeUser(await parseResponse(response));
}

export async function createGuestSession() {
  const response = await fetch(`${API_BASE_URL}/auth/guest`, {
    method: "POST",
    credentials: "include",
  });

  return normalizeUser(await parseResponse(response));
}

export async function createAdminSession(username, password) {
  const response = await fetch(`${API_BASE_URL}/auth/admin-login`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  return normalizeUser(await parseResponse(response));
}

export async function getCurrentUser({ signal } = {}) {
  const response = await fetch(`${API_BASE_URL}/auth/me`, {
    method: "GET",
    credentials: "include",
    signal,
  });

  if (response.status === 401) {
    return null;
  }

  return normalizeUser(await parseResponse(response));
}

export async function logoutSession() {
  const response = await fetch(`${API_BASE_URL}/auth/logout`, {
    method: "POST",
    credentials: "include",
  });

  if (response.status !== 401 && !response.ok) {
    await parseResponse(response);
  }
}

export function startSocialLogin(provider) {
  const returnUrl = `${window.location.origin}/login?auth=success`;
  const loginUrl = new URL(
    `${API_BASE_URL}/auth/${provider}/login`,
  );

  loginUrl.searchParams.set("return_url", returnUrl);
  window.location.assign(loginUrl.toString());
}
