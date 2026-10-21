import { getStore } from '@netlify/blobs';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { deployContext } from '../lib/deployment.mjs';
import { createService } from '../lib/service.mjs';
const handler=createService({
  store:()=>getStore({name:'marathon-private-v1',consistency:'strong'}),
  asset: name=>readFile(path.join(process.cwd(),'austin-plan/public',name)),
  env:{...process.env,CONTEXT:deployContext},
});
export default handler;

export const config={path:"/*",preferStatic:false};
