// One policy for visible buttons and direct/old interaction submissions.
function ownerOnly(id) {
  id=String(id||'');
  if(id.startsWith('admin_ops_duplicate_refund:')||id.startsWith('admin_ops_resolve:duplicate_refund:'))return true;
  return /^(provider_|admin_railway_|admin_owner_|admin_upgrade_|admin_df_|admin_smscode_webhook|admin_ops_low|admin_store_maintenance|admin_tools_(backup|report|csv|fee|audit)|admin_healthcheck_(midtrans|invoice|callbacks|errors|alerts|refund))/.test(id)
    || ['admin_digiflazz','admin_health','admin_test_otp','admin_system_provider','admin_catalog_provider','admin_reports_menu','admin_healthcheck','admin_healthcheck_dm','admin_ops_manual','admin_ops_manual_save','admin_store_maintenance'].includes(id);
}
function privateMenu(payload,isOwner,canAccess=()=>true) {
  if(isOwner)return payload;
  if(!payload||typeof payload!=='object'||!Array.isArray(payload.components))return payload;
  return {...payload,components:payload.components.map(row=>{
    const data=typeof row.toJSON==='function'?row.toJSON():row;
    return {...data,components:(data.components||[]).filter(item=>(isOwner||!ownerOnly(item.custom_id||item.customId))&&(!String(item.custom_id||item.customId||'').startsWith('admin_')||canAccess(item.custom_id||item.customId)))};
  }).filter(row=>row.components.length)};
}
async function protectOwnerInteraction(i,staff) {
  if((ownerOnly(i.customId)&&!staff.isOwner(i.user.id))||(String(i.customId||'').startsWith('admin_')&&staff.canRoute&&!staff.canRoute(i.user.id,i.customId))) {
    await i.reply({ephemeral:true,content:ownerOnly(i.customId)?'Akses ditolak. Fitur privat ini khusus owner toko.':'Akses ditolak. Izin fitur ini tidak diberikan untuk peran Anda.'});return true;
  }
  for(const method of ['reply','editReply','update','followUp'])if(typeof i[method]==='function') {
    const original=i[method].bind(i);
    i[method]=payload=>original(privateMenu(payload,staff.isOwner(i.user.id),id=>!staff.canRoute||staff.canRoute(i.user.id,id)));
  }
  return false;
}
module.exports={ownerOnly,privateMenu,protectOwnerInteraction};
