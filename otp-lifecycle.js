'use strict';
const WAIT=180000,TTL=1200000;
function time(v){if(typeof v!=='string'||!v)return null;const n=Date.parse(/^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d$/.test(v)?v.replace(' ','T')+'Z':v);return Number.isFinite(n)?n:null;}
function createOTPLifecycle({db,fetchOrder,resendOrder,now=Date.now}){
 db.exec('CREATE TABLE IF NOT EXISTS otp_lifecycle(provider_id TEXT PRIMARY KEY,meta TEXT NOT NULL,resend_attempt_ms INTEGER NOT NULL DEFAULT 0)');
 const locks=new Set();
 function observe(d){if(!d?.id)return;const id=String(d.id),old=db.prepare('SELECT * FROM otp_lifecycle WHERE provider_id=?').get(id),m=old?JSON.parse(old.meta):{};const revision=Number.isSafeInteger(d.sms_revision)?d.sms_revision:null;if(revision!==null&&m.revision!=null&&revision<m.revision)return m;
  const local=db.prepare('SELECT * FROM orders WHERE provider_order_id=? LIMIT 1').get(id);
  m.start=m.start??time(d.created_at)??time(local?.created_at)??now();m.expires=time(d.expires_at)??m.expires??m.start+TTL;const incoming=String(d.status||m.status||local?.status||'ACTIVE').toUpperCase();m.status=['COMPLETED','CANCELED','CANCELLED','EXPIRED','FAILED'].includes(m.status)&&['ACTIVE','PENDING','OTP_RECEIVED'].includes(incoming)?m.status:incoming;m.hasSMS=!!(m.hasSMS||d.otp_code||d.otp_message||d.otp_received_at||d.sms_revision>0||local?.otp||local?.otp_message||['OTP_RECEIVED','COMPLETED'].includes(m.status));
  if(typeof d.can_cancel==='boolean')m.canCancel=d.can_cancel;if(typeof d.can_resend==='boolean')m.canResend=d.can_resend;m.cancelAt=time(d.cancel_available_at)??m.cancelAt??0;m.resendAt=time(d.resend_available_at)??m.resendAt??0;if(m.awaitingResend&&((d.otp_code&&String(d.otp_code)!==m.resendCode)||(!d.otp_code&&d.otp_message&&revision!==null&&revision>(m.resendRevision??-1))))m.awaitingResend=false;if(revision!==null)m.revision=revision;
  db.prepare('INSERT INTO otp_lifecycle(provider_id,meta) VALUES(?,?) ON CONFLICT(provider_id) DO UPDATE SET meta=excluded.meta').run(id,JSON.stringify(m));return m;
 }
 function owned(id,user){const o=db.prepare('SELECT * FROM orders WHERE provider_order_id=? AND discord_id=?').get(String(id),String(user));if(!o)throw Error('Order tidak ditemukan.');return o;}
 function state(id,user){const o=owned(id,user),saved=db.prepare('SELECT * FROM otp_lifecycle WHERE provider_id=?').get(String(id)),m=saved?JSON.parse(saved.meta):observe({id,status:o.status,created_at:o.created_at,otp_code:o.otp,otp_message:o.otp_message});const active=['ACTIVE','OTP_RECEIVED','PENDING'].includes(m.status)&&!o.refunded,waitUntil=m.start+WAIT,remaining=Math.max(0,m.expires-now());const cancelReady=active&&remaining>0&&!m.hasSMS&&m.canCancel!==false&&now()>=Math.max(waitUntil,m.cancelAt);const resendReady=active&&remaining>0&&m.canResend===true&&now()>=Math.max(waitUntil,m.resendAt,(saved?.resend_attempt_ms||0)+30000);return {order:o,...m,resendAttempt:saved?.resend_attempt_ms||0,remaining,waitUntil,cancelReady,resendReady};}
 async function refresh(id,user){owned(id,user);const r=await fetchOrder(id),d=r?.data;if(!d||String(d.id)!==String(id))throw Error('Status provider belum valid. Coba Cek OTP lagi.');const before=db.prepare('SELECT meta FROM otp_lifecycle WHERE provider_id=?').get(String(id)),revision=before?JSON.parse(before.meta).revision:null;if(Number.isSafeInteger(d.sms_revision)&&revision!=null&&d.sms_revision<revision)throw Error('Status SMS lama diabaikan. Cek kembali.');const observed=observe(d);const cols=db.prepare('PRAGMA table_info(orders)').all().map(c=>c.name);db.prepare('UPDATE orders SET status=?,otp=COALESCE(?,otp),phone=COALESCE(?,phone) WHERE provider_order_id=? AND discord_id=? AND refunded=0').run(observed.status,d.otp_code||null,d.phone_number||null,String(id),String(user));if(cols.includes('otp_message')&&d.otp_message)db.prepare('UPDATE orders SET otp_message=? WHERE provider_order_id=? AND discord_id=? AND refunded=0').run(d.otp_message,String(id),String(user));return state(id,user);}
 async function assertCancel(order){const s=await refresh(order.provider_order_id,order.discord_id);if(!s.cancelReady){if(s.hasSMS)throw Error('SMS/OTP sudah diterima. Order tidak dapat dibatalkan.');if(now()<s.waitUntil)throw Error('Cancel aktif setelah 3 menit (sisa 17 menit pada order 20 menit).');throw Error('Provider belum mengizinkan pembatalan order ini.');}return s;}
 async function resend(id,user){owned(id,user);if(locks.has(String(id)))throw Error('Permintaan kirim ulang sedang diproses.');locks.add(String(id));try{const s=await refresh(id,user);if(!s.resendReady)throw Error(now()<s.waitUntil?'Kirim ulang aktif setelah 3 menit.':'Provider belum mengizinkan kirim ulang, masa order habis, atau masih dalam jeda.');db.prepare('UPDATE otp_lifecycle SET resend_attempt_ms=? WHERE provider_id=?').run(now(),String(id));const r=await resendOrder(id);if(r?.data?.resent!==true||String(r.data.order_id)!==String(id))throw Error('Provider tidak mengonfirmasi kirim ulang. Kode baru belum tersedia.');const m=JSON.parse(db.prepare('SELECT meta FROM otp_lifecycle WHERE provider_id=?').get(String(id)).meta);m.awaitingResend=true;m.resendCode=String(s.order.otp||'');m.resendRevision=m.revision??0;db.prepare('UPDATE otp_lifecycle SET meta=? WHERE provider_id=?').run(JSON.stringify(m),String(id));return state(id,user);}finally{locks.delete(String(id));}}
 return {observe,state,refresh,assertCancel,resend};
}
function createOTPLifecycleHandler({discord,model,commerce}){
 const {ActionRowBuilder,ButtonBuilder}=discord;
 const escape=v=>String(v||'-').replace(/[\\`*_{}\[\]()<>~|]/g,'\\$&');
 function panel(id,user){const s=model.state(id,user),seconds=Math.ceil(s.remaining/1000),left=Math.floor(seconds/60)+':'+String(seconds%60).padStart(2,'0');return {content:'**Order OTP '+escape(id)+'**\nNomor: '+escape(s.order.phone)+'\nStatus: '+escape(s.status)+'\nSisa waktu: **'+left+'** • batas <t:'+Math.floor(s.expires/1000)+':R>\n'+(s.order.otp?(s.awaitingResend?'OTP sebelumnya (menunggu baru): **':'OTP: **')+escape(s.order.otp)+'**\n':s.order.otp_message?'SMS: '+escape(s.order.otp_message).slice(0,650)+'\n':'Belum ada OTP.\n')+(s.awaitingResend?'Menunggu SMS/kode baru dari provider.\n':'')+'Cancel/Kirim Ulang mulai setelah 3 menit, mengikuti izin SMSCode.\nTekan Cek OTP untuk memperbarui waktu dan tombol.',allowedMentions:{parse:[]},components:[new ActionRowBuilder().addComponents(new ButtonBuilder().setCustomId('check_otp:'+id).setLabel('Cek OTP / Perbarui').setStyle(3),new ButtonBuilder().setCustomId('cancel_order:'+id).setLabel('Cancel / Ganti Nomor').setStyle(4).setDisabled(!s.cancelReady),new ButtonBuilder().setCustomId('resend_order:'+id).setLabel('Kirim Ulang Kode').setStyle(1).setDisabled(!s.resendReady),new ButtonBuilder().setCustomId('copy_otp_phone:'+id).setLabel('Ambil Nomor').setStyle(2))]};}
 const handle=async i=>{
  if(!/^(check_otp|cancel_order|resend_order|copy_otp_phone):/.test(String(i.customId||'')))return false;
  const [action,id]=i.customId.split(':');
  // Only edit a private panel, and only after checking who owns the order.
  const update=action!=='copy_otp_phone'&&i.isButton?.()&&i.message?.flags?.has?.(64)&&typeof i.deferUpdate==='function';
  if(update){try{model.state(id,i.user.id);}catch{await i.reply({ephemeral:true,content:'Order tidak ditemukan.',allowedMentions:{parse:[]}});return true;}await i.deferUpdate();}
  else await i.deferReply({ephemeral:true});
  try{
   if(action==='copy_otp_phone'){
    const phone=String(model.state(id,i.user.id).order.phone||'').trim();
    if(!/^\+?[0-9]{5,20}$/.test(phone))throw Error('Nomor belum tersedia atau format nomor tidak valid.');
    await i.editReply({content:phone,allowedMentions:{parse:[]},components:[]});
   }else if(action==='cancel_order'){
    const old=model.state(id,i.user.id).order,refund=await commerce.cancel(id,i.user.id);
    const owner=String(old.product_name||'').startsWith('[OWNER]');
    await i.editReply({content:'✅ Order dibatalkan. '+(owner?'Refund biaya provider dikonfirmasi SMSCode.':'Refund ke saldo: '+refund+' IDR.')+'\nUntuk ganti nomor, lanjutkan pembelian baru dengan harga dan stok terbaru. Nomor baru menunggu konfirmasi pembayaran.',embeds:[],allowedMentions:{parse:[]},components:[new ActionRowBuilder().addComponents(new ButtonBuilder().setCustomId(owner?'provider_catalog':'buy_again:'+old.id).setLabel('Pilih Nomor Baru').setStyle(1))]});
   }else{
    if(action==='resend_order')await model.resend(id,i.user.id);else await model.refresh(id,i.user.id);
    const p=panel(id,i.user.id);p.embeds=[];
    if(action==='resend_order')p.content='✅ Resend diterima provider. Waktu order tetap mengikuti SMSCode.\n\n'+p.content;
    await i.editReply(p);
   }
  }catch(e){let p;try{p=panel(id,i.user.id);}catch{}await i.editReply({...(p||{}),content:'❌ '+String(e.message).slice(0,650)+(p?'\n\n'+p.content:''),embeds:[],allowedMentions:{parse:[]},...(!p?{components:[]}:{})});}
  return true;
 };handle.panel=panel;return handle;
}
module.exports={createOTPLifecycle,createOTPLifecycleHandler};
