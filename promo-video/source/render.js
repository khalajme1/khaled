const {chromium}=require('playwright');
const [,,dir,mode]=process.argv;
(async()=>{
 const b=await chromium.launch(); const pg=await b.newPage({viewport:{width:1080,height:1920}});
 await pg.goto('file://'+dir+'/index.html'); await pg.evaluate(()=>document.fonts.ready);
 await pg.waitForTimeout(500);
 if(mode==='preview'){ for(const t of [2.5,8,14,20.5]){await pg.evaluate(t=>render(t),t);await pg.screenshot({path:`${dir}/prev_${t}.jpg`,quality:70});} }
 else { require('fs').mkdirSync(dir+'/frames',{recursive:true}); const fps=30,N=22*fps;
   for(let i=0;i<N;i++){await pg.evaluate(t=>render(t),i/fps);await pg.screenshot({path:`${dir}/frames/f${String(i).padStart(4,'0')}.jpg`,quality:92,type:'jpeg'});} }
 await b.close();})();
