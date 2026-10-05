const {randomUUID}=require('node:crypto');
function createCommerce({db,pricing,smsCreateOrder,smsCancel,assertOpen=()=>{},checkPurchase=()=>{}}) {
  const columns=db.prepare('PRAGMA table_info(orders)').all().map(c=>c.name);
  if(!columns.includes('provider_amount'))db.exec('ALTER TABLE orders ADD COLUMN provider_amount INTEGER');
  if(!columns.includes('refunded'))db.exec('ALTER TABLE orders ADD COLUMN refunded INTEGER NOT NULL DEFAULT 0');
  for(const name of ['platform_id','country_id','operator_id','product_name'])if(!columns.includes(name))db.exec(`ALTER TABLE orders ADD COLUMN ${name} TEXT`);
  for(const [name,type] of Object.entries({voucher_code:"TEXT",discount_amount:"INTEGER NOT NULL DEFAULT 0",original_amount:"INTEGER"}))if(!db.prepare("PRAGMA table_info(orders)").all().some(c=>c.name===name))db.exec(`ALTER TABLE orders ADD COLUMN ${name} ${type}`);
  if(!columns.includes('is_owner_test'))db.exec('ALTER TABLE orders ADD COLUMN is_owner_test INTEGER NOT NULL DEFAULT 0');
  db.exec(`CREATE TABLE IF NOT EXISTS otp_wallet_attempts (
    token TEXT PRIMARY KEY,discord_id TEXT NOT NULL,quote_json TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'processing',provider_order_id TEXT,error TEXT,
    resolved_by TEXT,note TEXT,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
  );
  CREATE INDEX IF NOT EXISTS otp_wallet_attempt_user ON otp_wallet_attempts(discord_id,state);
  CREATE UNIQUE INDEX IF NOT EXISTS otp_wallet_one_pending ON otp_wallet_attempts(discord_id) WHERE state IN ('processing','review','resolving');`);
  db.prepare("UPDATE otp_wallet_attempts SET state='review',error='Proses terputus; periksa riwayat SMSCode sebelum membeli lagi.' WHERE state IN ('processing','resolving')").run();
  let otpPolicy=null,coupons,isOwner=()=>false;
  const checkouts=new Map();const locks=new Set();const cancelLocks=new Set();
  const linked=id=>db.prepare('SELECT id FROM orders WHERE provider_order_id=?').get(String(id));
  const unresolved=user=>db.prepare("SELECT * FROM otp_wallet_attempts WHERE discord_id=? AND state IN ('processing','review','resolving') LIMIT 1").get(user);
  function saveOrder(userId,q,order) {
    if(linked(order.id))throw Error('ID order provider sudah tercatat. Transaksi duplikat ditolak.');
    if(!q.ownerOnly)checkPurchase('otp',userId,q.amount);
    if(q.ownerOnly&&!isOwner(userId))throw Error('Akses owner sudah dicabut.');
    if(!q.ownerOnly){const debit=db.prepare('UPDATE users SET balance=balance-? WHERE discord_id=? AND balance>=?').run(q.amount,userId,q.amount);
      if(!debit.changes)throw Error('Saldo tidak cukup.');
      coupons?.claim(userId,q,'wallet:'+String(order.id));}
    db.prepare('INSERT INTO orders(discord_id,product_id,provider_order_id,phone,otp,amount,provider_amount,status) VALUES(?,?,?,?,?,?,?,?)')
      .run(userId,q.productId,String(order.id),order.phone_number || null,order.otp_code || null,q.amount,q.providerAmount,order.status || 'ACTIVE');
    db.prepare('UPDATE orders SET platform_id=?,country_id=?,operator_id=?,product_name=?,voucher_code=?,discount_amount=?,original_amount=?,is_owner_test=? WHERE provider_order_id=? AND discord_id=?')
      .run(q.platformId==null?null:String(q.platformId),q.countryId==null?null:String(q.countryId),q.operatorId==null?null:String(q.operatorId),q.name,q.coupon || null,q.discount || 0,q.originalAmount ?? q.amount,q.ownerOnly?1:0,String(order.id),userId);
  }
  function quote(userId,product) {
    for(const [key,c] of checkouts)if(c.expires<Date.now())checkouts.delete(key);
    const providerAmount=Number(product.price?.canonical_amount ?? product.price);
    if(!Number.isSafeInteger(Number(product.id))||Number(product.id)<=0)throw Error('ID produk provider tidak valid.');
    const amount=pricing.price(providerAmount);const token=randomUUID();
    checkouts.set(token,{userId,productId:Number(product.id),providerAmount,amount,name:product.name || `Produk ${product.id}`,platformId:product.platform_id,countryId:product.country_id,operatorId:product.operator_id ?? null,expires:Date.now()+300000});
    return {token,amount,providerAmount};
  }
  async function buy(userId,token) {
    assertOpen();
    const q=checkouts.get(token);
    if(!q || q.userId!==userId || q.expires<Date.now())throw new Error('Konfirmasi kedaluwarsa. Pilih produk kembali.');
    if(!q.ownerOnly)checkPurchase('otp',userId,q.amount);
    if(q.ownerOnly&&!isOwner(userId))throw Error('Hanya owner boleh memakai saldo provider.');
    if(locks.has(userId))throw new Error('Pembelian sedang diproses. Tunggu hasilnya.');
    const pending=unresolved(userId);
    if(pending)throw Error('Transaksi OTP sebelumnya perlu diperiksa owner. Referensi: '+pending.token+'. Jangan membeli ulang.');
    if(!q.ownerOnly&&pricing.price(q.providerAmount)!==(q.originalAmount ?? q.amount))throw new Error('Harga jual berubah. Pilih produk kembali untuk melihat harga terbaru.');
    db.prepare('INSERT OR IGNORE INTO users(discord_id,balance) VALUES(?,0)').run(userId);
    if(!q.ownerOnly&&db.prepare('SELECT balance FROM users WHERE discord_id=?').get(userId).balance<q.amount)throw new Error('Saldo tidak cukup untuk harga jual produk.');
    db.prepare('INSERT INTO otp_wallet_attempts(token,discord_id,quote_json) VALUES(?,?,?)').run(token,userId,JSON.stringify(q));
    locks.add(userId);checkouts.delete(token);
    let order;let saved=false;
    try {
      const result=await smsCreateOrder(q.productId,{idempotencyKey:token});order=result.data?.orders?.[0];
      if(!order || !/^\d+$/.test(String(order.id)) || !Number.isSafeInteger(Number(order.id)) || Number(order.id)<=0)throw new Error('Provider tidak mengembalikan ID order yang valid.');
      db.prepare('UPDATE otp_wallet_attempts SET provider_order_id=? WHERE token=?').run(String(order.id),token);
      if(linked(order.id))throw Error('ID order provider sudah tercatat. Transaksi duplikat ditolak.');
      const providerAmount=Number(order.amount?.canonical_amount ?? order.amount);
      if(providerAmount!==q.providerAmount)throw new Error('Harga provider berubah. Order akan dibatalkan; pilih produk kembali.');
      db.transaction(()=>{
        saveOrder(userId,q,order);
        db.prepare("UPDATE otp_wallet_attempts SET state='fulfilled',error=NULL WHERE token=?").run(token);
      })();
      saved=true;return {order,amount:q.amount,providerAmount,ownerOnly:Boolean(q.ownerOnly)};
    } catch(error) {
      // Never cancel an ID already owned by an earlier transaction.
      let state='review';
      if(order?.id && /^\d+$/.test(String(order.id)) && Number.isSafeInteger(Number(order.id)) && Number(order.id)>0 && !saved && !linked(order.id)){
        try{await smsCancel(order.id);state='canceled';}catch{}
      }
      db.prepare('UPDATE otp_wallet_attempts SET state=?,error=? WHERE token=?').run(state,String(error.message).slice(0,500),token);
      if(state==='review')throw Error(error.message+' Hasil provider perlu diperiksa owner. Referensi: '+token+'. Jangan membeli ulang.');
      throw error;
    } finally {locks.delete(userId);}
  }
  async function resolveWallet(adminId,token,action,orderId,note,fetchOrder) {
    if(!isOwner(adminId))throw Error('Resolusi transaksi OTP khusus owner.');
    if(!['attach','cancel','absent','duplicate'].includes(action)||!String(note||'').trim()||String(note).length>300)throw Error('Pilih tindakan dan isi catatan maksimal 300 karakter.');
    const row=db.prepare('SELECT * FROM otp_wallet_attempts WHERE token=?').get(token);
    if(!row||row.state!=='review')throw Error('Transaksi tidak menunggu pemeriksaan.');
    if(!db.prepare("UPDATE otp_wallet_attempts SET state='resolving' WHERE token=? AND state='review'").run(token).changes)throw Error('Transaksi sedang diperiksa.');
    try{
      const q=JSON.parse(row.quote_json);let order;
      orderId=String(orderId||row.provider_order_id||'').trim();
      if(action==='duplicate'){
        if(!row.provider_order_id||orderId!==row.provider_order_id||!linked(orderId))throw Error('Tidak ada duplikasi order tercatat untuk transaksi ini.');
      }else if(action==='absent'){
        if(orderId)throw Error('ID order tersedia. Periksa dan batalkan melalui provider terlebih dahulu.');
        if(!String(note).startsWith('TIDAK ADA ORDER:'))throw Error('Periksa riwayat SMSCode lalu awali catatan dengan TIDAK ADA ORDER:');
      }else{
        if(!/^\d+$/.test(orderId)||!Number.isSafeInteger(Number(orderId))||Number(orderId)<=0)throw Error('ID order provider tidak valid.');
        if(row.provider_order_id&&orderId!==row.provider_order_id)throw Error('ID berbeda dari order yang tercatat.');
        if(linked(orderId))throw Error('Order sudah terhubung ke transaksi lain.');
        order=(await fetchOrder(orderId))?.data;
        if(!order||String(order.id)!==orderId||Number(order.product_id)!==q.productId)throw Error('Order provider tidak sesuai produk transaksi.');
        if(action==='attach'&&Number(order.amount?.canonical_amount??order.amount)!==q.providerAmount)throw Error('Biaya provider tidak sesuai. Gunakan pemeriksaan/pembatalan.');
        if(action==='attach'&&(!order.phone_number||!['ACTIVE','OTP_RECEIVED','COMPLETED'].includes(String(order.status).toUpperCase())||(order.operator_id==null?null:String(order.operator_id))!==(q.operatorId==null?null:String(q.operatorId))))throw Error('Order harus aktif/sudah menerima OTP, dengan nomor dan operator sesuai transaksi.');
        if(action==='cancel'&&String(order.status).toUpperCase()!=='CANCELED')await smsCancel(orderId);
      }
      db.transaction(()=>{
        if(!isOwner(adminId))throw Error('Akses owner sudah dicabut.');
        if(action==='attach')saveOrder(row.discord_id,q,order);
        const changed=db.prepare("UPDATE otp_wallet_attempts SET state=?,provider_order_id=?,error=NULL,resolved_by=?,note=? WHERE token=? AND state='resolving'")
          .run(action==='attach'?'fulfilled':'canceled',orderId||null,adminId,String(note).trim(),token);
        if(!changed.changes)throw Error('Status pemeriksaan berubah.');
      })();
      return {state:action==='attach'?'fulfilled':'canceled',amount:action==='attach'?q.amount:0};
    }catch(e){db.prepare("UPDATE otp_wallet_attempts SET state='review',error=? WHERE token=? AND state='resolving'").run(String(e.message).slice(0,500),token);throw e;}
  }
  async function cancel(orderId,userId) {
    const order=db.prepare('SELECT * FROM orders WHERE provider_order_id=? AND discord_id=?').get(String(orderId),userId);
    if(!order)throw new Error('Order tidak ditemukan.');
    if(order.refunded || (order.status==='CANCELED' && order.provider_amount==null))return 0;
    if(order.otp || ['COMPLETED','OTP_RECEIVED'].includes(order.status))throw new Error('Order sudah menerima OTP atau selesai.');
    if(cancelLocks.has(String(orderId)))throw new Error('Pembatalan sedang diproses.');
    cancelLocks.add(String(orderId));
    try {
      if(otpPolicy)await otpPolicy.assertCancel(order);
      await smsCancel(orderId);
      return db.transaction(()=>{
        const updated=db.prepare("UPDATE orders SET status='CANCELED',refunded=1 WHERE id=? AND refunded=0").run(order.id);
        if(!updated.changes)return 0;
        db.prepare('UPDATE users SET balance=balance+? WHERE discord_id=?').run(order.amount,userId);
        return order.amount;
      })();
    } finally {cancelLocks.delete(String(orderId));}
  }
  return {resolveWallet,walletIssues:()=>db.prepare("SELECT * FROM otp_wallet_attempts WHERE state='review' ORDER BY created_at,token LIMIT 10").all(),setOTPPolicy:policy=>otpPolicy=policy,quote,buy,cancel,async ownerBuy(userId,token){const q=checkouts.get(token);if(!isOwner(userId)||!q?.ownerOnly)throw Error('Hanya konfirmasi saldo provider owner yang boleh diproses.');return buy(userId,token);},setOwnerAccess:check=>isOwner=check,ownerQuote(userId,product){if(!isOwner(userId))throw Error('Hanya owner boleh memakai saldo provider.');const q=quote(userId,product),saved=checkouts.get(q.token);Object.assign(saved,{ownerOnly:true,amount:0,name:'[OWNER] '+saved.name});return {...q,amount:0};},setCoupons:engine=>coupons=engine,
    applyCoupon(userId,token,code){const q=this.checkout(userId,token);const d=coupons.discount(userId,code,q);const saved=checkouts.get(token);Object.assign(saved,{originalAmount:d.originalAmount,amount:d.amount,discount:d.discount,coupon:d.code});return {...saved};},
    claimCoupon(userId,q,reference,invoice){coupons?.claim(userId,q,reference,invoice);},checkout(userId,token,consume=false){
    const q=checkouts.get(token);
    if(!q || q.userId!==userId || q.expires<Date.now())throw new Error('Konfirmasi kedaluwarsa. Pilih produk kembali.');
    if(q.ownerOnly)throw Error('Konfirmasi owner hanya untuk saldo provider.');
    if(pricing.price(q.providerAmount)!==(q.originalAmount ?? q.amount))throw new Error('Harga jual berubah. Pilih produk kembali.');
    if(consume)checkouts.delete(token);
    return {...q};
  }};
}
module.exports={createCommerce};
