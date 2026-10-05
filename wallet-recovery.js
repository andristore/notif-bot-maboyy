'use strict';
function createWalletRecoveryHandler({discord,commerce,staff,fetchOrder}) {
  const {ActionRowBuilder,ButtonBuilder,ModalBuilder,TextInputBuilder,TextInputStyle}=discord;
  const menu='admin_owner_wallet_issues';
  const button=(id,label)=>new ButtonBuilder().setCustomId(id).setLabel(label).setStyle(1);
  return async i=>{
    const id=String(i.customId||'');
    if(!id.startsWith('admin_owner_wallet_'))return false;
    if(!staff.isOwner(i.user.id)){await i.reply({ephemeral:true,content:'Pemeriksaan transaksi OTP khusus owner.'});return true;}
    if(id.startsWith('admin_owner_wallet_open:')){
      const token=id.split(':')[1];
      if(!commerce.walletIssues().some(r=>r.token===token)){await i.reply({ephemeral:true,content:'Transaksi sudah diselesaikan atau tidak ditemukan.'});return true;}
      const field=(key,label,max,required=true)=>new ActionRowBuilder().addComponents(new TextInputBuilder().setCustomId(key).setLabel(label).setStyle(TextInputStyle.Short).setRequired(required).setMaxLength(max));
      await i.showModal(new ModalBuilder().setCustomId('admin_owner_wallet_save:'+token).setTitle('Periksa OTP Saldo')
        .addComponents(field('action','Tindakan: attach / cancel / absent / duplicate',9),field('order','ID order SMSCode (jika tersedia)',20,false),field('note','Catatan pemeriksaan riwayat provider',300)));
      return true;
    }
    await i.deferReply({ephemeral:true});
    try{
      if(id.startsWith('admin_owner_wallet_save:')){
        const r=await commerce.resolveWallet(i.user.id,id.split(':')[1],i.fields.getTextInputValue('action').trim().toLowerCase(),i.fields.getTextInputValue('order').trim(),i.fields.getTextInputValue('note').trim(),fetchOrder);
        await i.editReply({content:r.state==='fulfilled'?'✅ Order dihubungkan. Saldo dipotong '+r.amount+' IDR satu kali.':'✅ Pemeriksaan ditutup. Saldo tidak dipotong dan tidak ditambahkan.',components:[new ActionRowBuilder().addComponents(button(menu,'Kembali'))],allowedMentions:{parse:[]}});
      }else if(id===menu){
        const rows=commerce.walletIssues();
        const details=rows.map(r=>{const q=JSON.parse(r.quote_json);return 'Referensi: '+r.token+'\nPembeli: '+r.discord_id+' • '+q.amount+' IDR\nOrder provider: '+(r.provider_order_id||'Belum diketahui');}).join('\n\n');
        const choices=rows.map((r,n)=>button('admin_owner_wallet_open:'+r.token,'Periksa '+(n+1)));
        const components=[];for(let n=0;n<choices.length;n+=5)components.push(new ActionRowBuilder().addComponents(...choices.slice(n,n+5)));
        components.push(new ActionRowBuilder().addComponents(button(menu,'Perbarui'),button('admin_payment_checks','Kembali')));
        await i.editReply({content:'**OTP Saldo Perlu Diperiksa**\n'+(rows.length?details:'Tidak ada transaksi menunggu pemeriksaan.')+'\n\nSaldo belum dipotong. Cocokkan riwayat SMSCode dan pembeli.\nattach: hubungkan order yang benar dan potong saldo.\ncancel: batalkan order provider tanpa kredit saldo.\nduplicate: tutup jika ID sudah tercatat pada transaksi lain.\nabsent: hanya jika tidak ada order; awali catatan dengan TIDAK ADA ORDER:.\nMaksimal 10 ditampilkan; selesaikan lalu Perbarui.',components,allowedMentions:{parse:[]}});
      }else throw Error('Menu pemeriksaan tidak dikenali.');
    }catch(e){await i.editReply({content:'❌ '+String(e.message).slice(0,1000),components:[new ActionRowBuilder().addComponents(button(menu,'Kembali'))],allowedMentions:{parse:[]}});}
    return true;
  };
}
module.exports={createWalletRecoveryHandler};
