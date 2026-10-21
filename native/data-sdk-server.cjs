// One private worker per bounded batch. No TCP listener or browser.
const {loadSdk,applyModel}=require('./data-sdk-host.cjs');
const readline=require('node:readline');
const send=value=>process.stdout.write('JYMODEL:'+JSON.stringify(value)+'\n');
try {
  const sdk=loadSdk(process.argv[2]);
  send({type:'ready'});
  const lines=readline.createInterface({input:process.stdin,crlfDelay:Infinity});
  lines.on('line',line=>{
    let request;
    try {
      if(Buffer.byteLength(line)>8*1024*1024)throw new Error('Draft-model request exceeds 8 MB');
      request=JSON.parse(line);
      send({id:request.id,ok:true,model:applyModel(sdk,request)});
    } catch(error) {
      send({id:request?.id,ok:false,error:String(error.message).slice(0,1000)});
    }
  });
} catch(error) {
  send({type:'fatal',error:String(error.message).slice(0,1000)});
  process.exitCode=1;
}
