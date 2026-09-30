import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const sourcesDir = path.join(__dirname, "sources", "sirens");

// Evidence fails on a CSV source without data rows, so an export that does
// not exist yet is seeded with one 1970 row that the pages filter out.
const PLACEHOLDERS = {
  "alerts_history.csv":
    "date,location,red_alerts,yellow_alerts\n1970-01-01 00:00:00,unknown,0,0\n",
  "message_views.csv":
    "posted_at,location,display_name,event_type,level,checkpoint_s,views\n" +
    "1970-01-01 00:00:00,unknown,unknown,air_raid_alert,,15,0\n",
};

fs.mkdirSync(sourcesDir, { recursive: true });

for (const [name, placeholder] of Object.entries(PLACEHOLDERS)) {
  const file = path.join(sourcesDir, name);
  const content = fs.existsSync(file) ? fs.readFileSync(file, "utf-8").trim() : "";
  const lines = content ? content.split("\n").filter(Boolean) : [];
  if (lines.length <= 1) {
    fs.writeFileSync(file, placeholder, "utf-8");
  }
}
