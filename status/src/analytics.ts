import { Env } from "./api";

const DEFAULT_MEASUREMENT_ID = "G-JC48ZJGBHM";

export function gaMeasurementId(env?: Env): string {
  if (env && env.ENVIRONMENT === "development") return "";

  const configured = env && env.GA_MEASUREMENT_ID;
  return (
    configured === undefined ? DEFAULT_MEASUREMENT_ID : configured
  ).trim();
}

export function analyticsHead(
  measurementId: string,
  systemState: string,
): string {
  if (!measurementId) return "";

  return `<link rel="preconnect" href="https://www.googletagmanager.com">
<!-- Google tag (gtag.js) -->
<script async src="https://www.googletagmanager.com/gtag/js?id=${measurementId}"></script>
<script>
window.dataLayer = window.dataLayer || [];
function gtag(){dataLayer.push(arguments);}
window.track = function (name, params) {
  try { gtag('event', name, params || {}); } catch (error) {}
};
gtag('js', new Date());
gtag('config', '${measurementId}', {
  page_type: 'status',
  system_state: '${systemState}'
});
</script>`;
}
