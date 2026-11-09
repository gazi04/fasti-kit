// k6 load test for the API. Run it with `just loadtest`; see docs/load-testing.md.
import http from "k6/http";
import exec from "k6/execution";
import { check, sleep } from "k6";

const BASE_URL = __ENV.BASE_URL || "http://load.fasti.localhost";
const VUS = Number(__ENV.VUS || 50);
const DURATION = __ENV.DURATION || "3m";
const USERS = Number(__ENV.USERS || 100);
const PASSWORD = __ENV.LOAD_PASSWORD || "load-test-password";
const LOGIN_RATE = Number(__ENV.LOGIN_RATE || 2);
const SIGNUP_RATE = Number(__ENV.SIGNUP_RATE || 1);

const RAMP = "30s";
const REFRESH_EVERY_SECONDS = 60;
const CSRF_COOKIE = "csrf_refresh_token";
const CSRF_HEADER = "X-CSRF-TOKEN";

// Each source of traffic gets its own slice of 198.18.0.0/15 (RFC 2544, benchmarking),
// so every virtual user or arrival has its own rate-limit bucket.
const IP_OFFSET = { browse: 0, logins: 40000, signups: 80000 };
const IP_SLICE = 40000;

export const options = {
  // A virtual user keeps its refresh cookie across iterations, like a browser.
  noCookiesReset: true,
  scenarios: {
    browse: {
      executor: "ramping-vus",
      exec: "browse",
      stages: [
        { duration: RAMP, target: VUS },
        { duration: DURATION, target: VUS },
        { duration: "15s", target: 0 },
      ],
    },
    logins: {
      executor: "constant-arrival-rate",
      exec: "loginOnly",
      rate: LOGIN_RATE,
      timeUnit: "1s",
      duration: DURATION,
      startTime: RAMP,
      preAllocatedVUs: 10,
      maxVUs: 200,
    },
    signups: {
      executor: "constant-arrival-rate",
      exec: "signup",
      rate: SIGNUP_RATE,
      timeUnit: "1s",
      duration: DURATION,
      startTime: RAMP,
      preAllocatedVUs: 5,
      maxVUs: 25,
    },
  },
  thresholds: {
    http_req_failed: ["rate<0.01"],
    checks: ["rate>0.99"],
    "http_req_duration{name:me}": ["p(95)<150"],
    "http_req_duration{name:update_me}": ["p(95)<300"],
    "http_req_duration{name:refresh}": ["p(95)<300"],
    "http_req_duration{name:login}": ["p(95)<1500"],
    "http_req_duration{name:signup}": ["p(95)<1500"],
  },
  summaryTrendStats: ["avg", "med", "p(90)", "p(95)", "p(99)", "max"],
};

function clientIp(scenario, n) {
  const index = IP_OFFSET[scenario] + (n % IP_SLICE);
  return `198.${18 + (index >> 16)}.${(index >> 8) & 255}.${index & 255}`;
}

function jsonHeaders(ip, token) {
  const headers = { "Content-Type": "application/json", "X-Forwarded-For": ip };
  if (token) headers.Authorization = `Bearer ${token}`;
  return headers;
}

function login(email, ip) {
  const response = http.post(
    `${BASE_URL}/api/v1/auth/login`,
    JSON.stringify({ email, password: PASSWORD }),
    { headers: jsonHeaders(ip), tags: { name: "login" } },
  );
  check(response, { "login 200": (r) => r.status === 200 });
  return response.status === 200 ? response.json("access_token") : null;
}

function loadUserEmail(n) {
  return `load-${n % USERS}@example.com`;
}

let accessToken = null;
let lastRefresh = 0;

function refresh(ip) {
  const csrf = http.cookieJar().cookiesForURL(BASE_URL)[CSRF_COOKIE];
  const headers = jsonHeaders(ip);
  headers[CSRF_HEADER] = csrf ? csrf[0] : "";
  const response = http.post(`${BASE_URL}/api/v1/auth/refresh`, null, {
    headers,
    tags: { name: "refresh" },
  });
  check(response, { "refresh 200": (r) => r.status === 200 });
  if (response.status === 200) accessToken = response.json("access_token");
}

export function browse() {
  const ip = clientIp("browse", exec.vu.idInTest);
  const now = Date.now() / 1000;

  if (accessToken === null) {
    accessToken = login(loadUserEmail(exec.vu.idInTest - 1), ip);
    lastRefresh = now;
    if (accessToken === null) {
      sleep(1);
      return;
    }
  } else if (now - lastRefresh >= REFRESH_EVERY_SECONDS) {
    refresh(ip);
    lastRefresh = now;
  }

  if (Math.random() < 0.9) {
    const response = http.get(`${BASE_URL}/api/v1/users/me`, {
      headers: jsonHeaders(ip, accessToken),
      tags: { name: "me" },
    });
    check(response, { "me 200": (r) => r.status === 200 });
  } else {
    const response = http.patch(
      `${BASE_URL}/api/v1/users/me`,
      JSON.stringify({ full_name: `Load User ${exec.vu.idInTest}-${exec.vu.iterationInScenario}` }),
      { headers: jsonHeaders(ip, accessToken), tags: { name: "update_me" } },
    );
    check(response, { "update_me 200": (r) => r.status === 200 });
  }

  sleep(0.5 + Math.random());
}

export function loginOnly() {
  const n = exec.scenario.iterationInTest;
  login(loadUserEmail(n), clientIp("logins", n));
}

export function signup() {
  const n = exec.scenario.iterationInTest;
  const response = http.post(
    `${BASE_URL}/api/v1/users`,
    JSON.stringify({
      name: "Load Signup",
      email: `k6-${Date.now()}-${n}-${exec.vu.idInTest}@example.com`,
      password: PASSWORD,
    }),
    { headers: jsonHeaders(clientIp("signups", n)), tags: { name: "signup" } },
  );
  check(response, { "signup 200": (r) => r.status === 200 });
}
