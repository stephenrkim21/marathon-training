import { access, writeFile } from 'node:fs/promises';
for (const file of ['austin-plan/public/index.html','austin-plan/public/app.js','austin-plan/public/plan.json','netlify/functions/app.mjs']) await access(file);
console.log('Private function bundle ready; no workout data published as static files.');

await writeFile('netlify/lib/deployment.mjs',`export const deployContext=${JSON.stringify(process.env.CONTEXT??'development')};\n`);
