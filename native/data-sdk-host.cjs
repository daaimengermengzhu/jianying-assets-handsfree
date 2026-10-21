// Use the locally installed draft model without launching a browser or networking.
// Its complete snapshot is NOT an output draft; Python merges selected changes only.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function loadSdk(install) {
  const root = path.join(install, 'Resources/canvas_agent/app/static/js');
  const chunks = [];
  const silent = {log(){}, warn(){}, error(){}, info(){}, debug(){}};
  const context = vm.createContext({self:{webpackChunkai_creation:chunks}, console:silent,
    TextEncoder, TextDecoder, Uint8Array, ArrayBuffer, DataView, URL, URLSearchParams,
    setTimeout, clearTimeout});
  for (const file of fs.readdirSync(root).filter(f=>/^(?:ai-creation~\d+|initial-vendors-[^.]+|lib-[^.]+|byted-image)\..*\.js$/.test(f))) {
    vm.runInContext(fs.readFileSync(path.join(root,file),'utf8'),context,{filename:file,timeout:2000});
  }
  const factories = Object.assign({}, ...chunks.map(c=>c[1]));
  const cache = {};
  function req(id) {
    if (cache[id]) return cache[id].exports;
    if (!factories[id]) throw new Error('Missing installed draft-model dependency');
    const module=cache[id]={exports:{}};
    factories[id](module,module.exports,req);
    return module.exports;
  }
  req.d=(exports,defs)=>{for(const key of Object.keys(defs)) if(!Object.hasOwn(exports,key)) Object.defineProperty(exports,key,{enumerable:true,get:defs[key]});};
  req.r=exports=>Object.defineProperty(exports,'__esModule',{value:true});
  req.o=(obj,key)=>Object.hasOwn(obj,key);
  req.n=mod=>{const getter=mod&&mod.__esModule?()=>mod.default:()=>mod;req.d(getter,{a:getter});return getter;};
  req.g=context; req.hmd=mod=>mod; req.nmd=mod=>mod;
  const candidates=Object.keys(factories).filter(k=>factories[k].toString().includes('DataSdk:function'));
  if(candidates.length!==1)throw new Error('Installed draft-model version is unsupported');
  return req(candidates[0]);
}

function applyModel(sdk,input) {
  if(!['sticker','subtitle-template','stock-video'].includes(input.kind))throw new Error('Unsupported draft operation');
  const data=new sdk.DataSdk();
  try {
  const aborts=[];
  data.onAbort(error=>aborts.push(String(error)));
  data.recoveryDraft(sdk.JSONB.parse(JSON.stringify(input.snapshot)));
  const before=JSON.parse(data.getDraftStr());
  let result;
  const p=input.params;
  if(input.kind==='sticker') {
    const added=data.api.track.add({track:new sdk.Track({id:p.segInfo.segId+'-TRACK',
      type:sdk.PersistLVVETrackType.TrackTypeSticker,flag:0}),trackIndex:p.trackIndex});
    if(added?.ok!==true || aborts.length)throw new Error('Sticker track creation aborted');
    result=data.api.sticker.add(p);
  } else if(input.kind==='subtitle-template') {
    result=data.api.text.updateSubtitleTemplate(p);
  } else {
    p.videos=p.videos.map(v=>sdk.createVideoParamFromPlain({...v,
      type:sdk.PersistLVVEMetaType.MetaTypeVideo,
      size:sdk.createSizeParamFromPlain(v.size),clip:sdk.createClipParamFromPlain(v.clip),
      mediaInfo:sdk.createLvWebVideoMediaInfoFromPlain(v.mediaInfo)}));
    result=data.api.video.add(p);
  }
  // DataSdk can return ok:true even after onAbort. Treat either signal as failure.
  if(result?.ok!==true || aborts.length)throw new Error('Installed draft model aborted: '+aborts.join('; ').slice(0,500));
  const after=JSON.parse(data.getDraftStr());
  return {before,after};
  } finally { data.dispose(); }
}

module.exports={loadSdk,applyModel};
if(require.main===module) {
  try {
    const input=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
    if(fs.existsSync(input.output))throw new Error('Refusing to overwrite model result');
    input.snapshot=JSON.parse(fs.readFileSync(input.source,'utf8'));
    const result=applyModel(loadSdk(input.install),input);
    fs.writeFileSync(input.output,JSON.stringify(result),{flag:'wx'});
    console.log(JSON.stringify({ok:true,kind:input.kind}));
  } catch(error) {
    console.error(String(error.message).slice(0,1000));
    process.exitCode=1;
  }
}
