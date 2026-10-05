'use strict';
const {createHash}=require('node:crypto');
function validateRelease(release){
  if(!release||typeof release.version!=='string'||release.version.length>32||!/^\d+\.\d+(?:\.\d+)?$/.test(release.version)||!Array.isArray(release.changes)||!release.changes.length||release.changes.length>10||release.changes.some(x=>typeof x!=='string'||!x.trim()||x.length>250))throw Error('release.json tidak valid. Isi versi dan 1–10 catatan perubahan.');
  return {version:release.version,changes:[...release.changes]};
}
function createReleaseInfo({db,staff,release,resolveChannel}){
  release=validateRelease(release);
  db.exec(`CREATE TABLE IF NOT EXISTS shopm_release_config(id INTEGER PRIMARY KEY CHECK(id=1),channel_id TEXT,enabled INTEGER NOT NULL DEFAULT 0);
    INSERT OR IGNORE INTO shopm_release_config(id,enabled) VALUES(1,0);
    CREATE TABLE IF NOT EXISTS shopm_release_receipts(channel_id TEXT,version TEXT,state TEXT NOT NULL,message_id TEXT,PRIMARY KEY(channel_id,version));`);
  // A process can stop after Discord accepts a message and before SQLite saves it.
  db.prepare("UPDATE shopm_release_receipts SET state='review' WHERE state='sending'").run();
  let busy=false;
  const owner=id=>{if(!staff.isOwner(id))throw Error('Info Update khusus owner.');};
  const config=()=>db.prepare('SELECT * FROM shopm_release_config WHERE id=1').get();
  const receipt=channel=>db.prepare('SELECT * FROM shopm_release_receipts WHERE channel_id=? AND version=?').get(channel,release.version);
  const marker='Shop.M • Informasi Update Resmi • v'+release.version;
  const payload=()=>({allowedMentions:{parse:[]},embeds:[{color:0x3498db,title:'🚀 Shop.M Diperbarui',description:'Shop.M telah diperbarui ke **v'+release.version+'**.\n\n**Detail perubahan**\n'+release.changes.map(x=>'• '+x).join('\n'),fields:[{name:'Versi',value:'v'+release.version},{name:'Status',value:'🤖 Otomatis'}],footer:{text:marker}}]});
  async function channel(id){const c=await resolveChannel(id);if(!c||c.type!==0||!c.approved||!c.canSend)throw Error('Gunakan channel teks di server yang disetujui. Bot memerlukan izin Lihat Channel, Kirim Pesan, Embed Links dan Baca Riwayat Pesan.');return c;}
  async function configure(id,value){owner(id);value=String(value).trim();if(!/^\d{17,20}$/.test(value))throw Error('ID channel harus berupa 17–20 angka.');await channel(value);owner(id);if(busy)throw Error('Pengiriman sedang diproses. Coba lagi sesaat.');db.prepare('UPDATE shopm_release_config SET channel_id=?,enabled=1 WHERE id=1').run(value);}
  function toggle(id){owner(id);if(busy)throw Error('Pengiriman sedang diproses.');if(!config().channel_id)throw Error('Atur channel terlebih dahulu.');db.prepare('UPDATE shopm_release_config SET enabled=1-enabled WHERE id=1').run();}
  async function poll(){
    if(busy)return 'busy';const setting=config();if(!setting.enabled||!setting.channel_id)return 'disabled';
    if(receipt(setting.channel_id)?.state==='sent')return 'sent';
    busy=true;
    try{
      const c=await channel(setting.channel_id),prior=receipt(setting.channel_id);
      if(['review','sending'].includes(prior?.state)){
        const found=await c.findMessage(marker);
        if(found){db.prepare("UPDATE shopm_release_receipts SET state='sent',message_id=? WHERE channel_id=? AND version=?").run(found,setting.channel_id,release.version);return 'sent';}
        return 'review'; // Never blindly repeat a message whose delivery is unknown.
      }
      const claimed=prior?.state==='retry'?db.prepare("UPDATE shopm_release_receipts SET state='sending' WHERE channel_id=? AND version=? AND state='retry'").run(setting.channel_id,release.version):db.prepare("INSERT OR IGNORE INTO shopm_release_receipts(channel_id,version,state) VALUES(?,?,'sending')").run(setting.channel_id,release.version);
      if(!claimed.changes)return 'busy';
      let message;
      try{message=await c.send({...payload(),nonce:createHash('sha256').update(setting.channel_id+':'+release.version).digest('hex').slice(0,24),enforceNonce:true});if(!message?.id)throw Error('Tidak ada konfirmasi pengiriman.');}
      catch(e){const rejected=[400,401,403,404,429].includes(Number(e.status));db.prepare('UPDATE shopm_release_receipts SET state=? WHERE channel_id=? AND version=?').run(rejected?'retry':'review',setting.channel_id,release.version);return rejected?'retry':'review';}
      db.prepare("UPDATE shopm_release_receipts SET state='sent',message_id=? WHERE channel_id=? AND version=?").run(message.id,setting.channel_id,release.version);return 'sent';
    }finally{busy=false;}
  }
  function status(id){owner(id);const c=config();return {...c,version:release.version,state:receipt(c.channel_id)?.state||'pending'};}
  function acknowledge(id,messageId){owner(id);if(busy)throw Error('Pengiriman sedang diproses.');if(!/^\d{17,20}$/.test(String(messageId)))throw Error('ID pesan tidak valid.');const c=config();if(receipt(c.channel_id)?.state!=='review')throw Error('Tidak ada pengiriman yang perlu diperiksa.');}
  async function confirm(id,messageId){acknowledge(id,messageId);const setting=config(),c=await channel(setting.channel_id),found=await c.findMessage(marker,String(messageId));owner(id);if(busy||config().channel_id!==setting.channel_id)throw Error('Pengaturan berubah. Coba lagi.');if(!found)throw Error('Pesan harus dikirim oleh bot ini dan memuat versi yang sesuai.');db.prepare("UPDATE shopm_release_receipts SET state='sent',message_id=? WHERE channel_id=? AND version=? AND state='review'").run(found,setting.channel_id,release.version);}
  return {configure,toggle,poll,status,payload,confirm,sendForOwner:async id=>{owner(id);return poll();}};
}
function createReleaseInfoHandler({discord,model,staff}){
  const {ActionRowBuilder,ButtonBuilder,ModalBuilder,TextInputBuilder,TextInputStyle}=discord;
  const root='admin_owner_release';
  const button=(suffix,label)=>new ButtonBuilder().setCustomId(root+suffix).setLabel(label).setStyle(1);
  return async i=>{
    const id=String(i.customId||'');if(id!==root&&!id.startsWith(root+'_'))return false;
    if(!staff.isOwner(i.user.id)){await i.reply({ephemeral:true,content:'Info Update khusus owner.'});return true;}
    if(id===root+'_channel'||id===root+'_confirm'){
      const confirm=id.endsWith('_confirm');await i.showModal(new ModalBuilder().setCustomId(root+(confirm?'_confirm_save':'_save')).setTitle(confirm?'Konfirmasi Pesan Terkirim':'Channel Info Update').addComponents(new ActionRowBuilder().addComponents(new TextInputBuilder().setCustomId('value').setLabel(confirm?'ID pesan update yang sudah terkirim':'ID channel teks Discord').setStyle(TextInputStyle.Short).setRequired(true).setMinLength(17).setMaxLength(20))));return true;
    }
    await i.deferReply({ephemeral:true});
    try{
      if(id===root+'_save')await model.configure(i.user.id,i.fields.getTextInputValue('value'));
      else if(id===root+'_toggle')model.toggle(i.user.id);
      else if(id===root+'_confirm_save')await model.confirm(i.user.id,i.fields.getTextInputValue('value'));
      else if(id===root+'_check')await model.sendForOwner(i.user.id);
      else if(id===root+'_preview'){await i.editReply({...model.payload(),content:'Pratinjau pribadi. Pesan ini belum diumumkan ke channel.',components:[new ActionRowBuilder().addComponents(button('','Kembali'))]});return true;}
      else if(id!==root)throw Error('Menu Info Update tidak dikenali.');
      const s=model.status(i.user.id),labels={sent:'✅ Sudah diumumkan',pending:'Menunggu pengiriman',review:'⚠️ Hasil pengiriman belum pasti. Periksa channel. Gunakan Konfirmasi Pesan jika pesan sudah ada; bot tidak mengirim ulang otomatis.',retry:'Pengiriman ditolak Discord; akan dicoba kembali.',sending:'Sedang dikirim'};
      await i.editReply({content:'**Info Update Shop.M**\nVersi: **v'+s.version+'**\nChannel: '+(s.channel_id?'<#'+s.channel_id+'>':'Belum diatur')+'\nOtomatis: '+(s.enabled?'Aktif':'Nonaktif')+'\nStatus: '+labels[s.state]+'\n\nVersi baru diumumkan setelah bot menjalankan release.json terbaru. Simpan database pada penyimpanan persisten agar riwayat pengiriman tetap ada.',allowedMentions:{parse:[]},components:[new ActionRowBuilder().addComponents(button('_channel','Atur Channel'),button('_toggle','Aktif / Nonaktif'),button('_preview','Pratinjau'),button('_check','Kirim / Periksa')),new ActionRowBuilder().addComponents(button('_confirm','Konfirmasi Pesan'),new ButtonBuilder().setCustomId('admin_system_data').setLabel('Kembali').setStyle(1))]});
    }catch(e){await i.editReply({content:'❌ '+(String(e.message).startsWith('Info Update')||/channel|Channel|Pengiriman|pesan|Pesan|Pengaturan|pengiriman|release.json/.test(e.message)?String(e.message).slice(0,700):'Info Update belum dapat diproses. Periksa izin channel dan koneksi bot.'),allowedMentions:{parse:[]},components:[new ActionRowBuilder().addComponents(button('','Kembali'))]});}
    return true;
  };
}
module.exports={validateRelease,createReleaseInfo,createReleaseInfoHandler};
