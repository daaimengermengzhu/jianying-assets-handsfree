// Calls the locally installed Jianying addon in this isolated Bun process.
const path = require('node:path');
const readline = require('node:readline');
const root = process.env.JY_INSTALL_DIR;
if (!root) throw new Error('JY_INSTALL_DIR is required');
const addon = require(path.join(root, 'videoeditor_addon.node'));
const emit = value => process.stdout.write('JYNATIVE:' + JSON.stringify(value) + '\n');
const parse = value => typeof value === 'string' ? JSON.parse(value) : value;
async function main() {
  const initialized = parse(addon.initialize(JSON.stringify({modelsDir:path.join(root,'Resources','models')})));
  emit({type:'ready', result:initialized});
  if (!initialized.admissible) return;
  const input = readline.createInterface({input:process.stdin, crlfDelay:Infinity});
  for await (const line of input) {
    if (!line.trim()) continue;
    let req;
    try {
      req = JSON.parse(line);
      if (req.operation === '__shutdown') break;
      if (req.domain === 'player' && req.operation === 'captureFrame') {
        const {width, height} = req.params || {};
        if (!Number.isInteger(width) || !Number.isInteger(height) || width < 1 || height < 1 || width > 1920 || height > 1920)
          throw new Error('Frame dimensions must be integers between 1 and 1920');
        const packet = await addon.readFrame(req.targetId, width, height);
        emit({type:'response', id:req.id, result:{accepted:packet.byteLength > 0,
          packetBase64:Buffer.from(packet).toString('base64'), bytes:packet.byteLength}});
        continue;
      }
      const wire = req.domain === 'player'
        ? {...req.params, id:req.id, method:req.operation, params:req.params,
           sessionId:req.targetId, priority:req.priority || 'interactive', protocolVersion:1}
        : {...req, protocolVersion:1, priority:req.priority || 'interactive'};
      emit({type:'response', id:req.id, result:parse(await addon.invoke(JSON.stringify(wire)))});
    } catch (error) {
      emit({type:'error', id:req?.id, error:{name:error.name,message:error.message}});
    }
  }
}
main().catch(error => { emit({type:'fatal',error:error.message}); process.exitCode=1; })
  .finally(() => addon.shutdown?.());
