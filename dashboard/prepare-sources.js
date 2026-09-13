import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const alertsFile = path.join(__dirname, 'sources', 'sirens', 'alerts_history.csv');
const PLACEHOLDER =
	'date,district,red_alerts,yellow_alerts\n1970-01-01 00:00:00,unknown,0,0\n';

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
