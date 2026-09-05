import { Env } from "./api";

// Той самий measurement ID, що й на sirens.live: GA4 кладе свою cookie на
// батьківський домен, тож сесія переходить між sirens.live і
// status.sirens.live сама — окремого cross-domain налаштування не треба.
const DEFAULT_MEASUREMENT_ID = "G-JC48ZJGBHM";

export function gaMeasurementId(env?: Env): string {
    // Локальний `wrangler pages dev` не має слати нічого в бойову властивість.
    if (env && env.ENVIRONMENT === "development") return "";

    const configured = env && env.GA_MEASUREMENT_ID;
    return (configured === undefined ? DEFAULT_MEASUREMENT_ID : configured).trim();
}

// Сторінка оновлюється сама раз на хвилину, але вже не перезавантажується:
// status.js міняє картку на місці. Тож page_view знову означає рівно один
// живий захід, а про тихе оновлення звітує окрема подія звідти ж —
// вигадувати тут прапорці й гасити page_view більше нема потреби.
export function analyticsHead(measurementId: string, systemState: string): string {
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
