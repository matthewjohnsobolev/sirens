import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const alertsFile = path.join(__dirname, 'sources', 'sirens', 'alerts_history.csv');
const PLACEHOLDER =
	'date,event_type,level,district,channel_id\n1970-01-01 00:00:00,air_raid_alert,,,\n';

if (!fs.existsSync(alertsFile)) {
	fs.mkdirSync(path.dirname(alertsFile), { recursive: true });
	fs.writeFileSync(alertsFile, PLACEHOLDER, 'utf-8');
} else {
	const content = fs.readFileSync(alertsFile, 'utf-8').trim();
	const lines = content ? content.split('\n').filter(Boolean) : [];
	if (lines.length <= 1) {
		fs.writeFileSync(alertsFile, PLACEHOLDER, 'utf-8');
	}
}
