const {errorText}=require('./languages');
const {buyerLabel}=require('./buyer-profiles');
const {randomUUID}=require('node:crypto');
function createDirectPayments({db,payments,commerce,smsCatalogProducts,smsCreateOrder,smsCancel,assertOpen=()=>{},checkPurchase=()=>{}}) {
  db.exec(`CREATE TABLE IF NOT EXISTS direct_purchases (
    invoice_id TEXT PRIMARY KEY,quote_token TEXT UNIQUE NOT NULL,discord_id TEXT NOT NULL,
    product_id INTEGER NOT NULL,platform_id TEXT,country_id TEXT,name TEXT NOT NULL,
    provider_amount INTEGER NOT NULL,amount INTEGER NOT NULL,state TEXT NOT NULL DEFAULT 'pending',
    provider_order_id TEXT,error TEXT,notified INTEGER NOT NULL DEFAULT 0,polled_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
  )`);
  if(!db.prepare('PRAGMA table_info(direct_purchases)').all().some(c=>c.name==='operator_id'))db.exec('ALTER TABLE direct_purchases ADD COLUMN operator_id INTEGER');
  for(const [name,type] of Object.entries({voucher_code:"TEXT",discount_amount:"INTEGER NOT NULL DEFAULT 0",original_amount:"INTEGER"}))if(!db.prepare("PRAGMA table_info(direct_purchases)").all().some(c=>c.name===name))db.exec(`ALTER TABLE direct_purchases ADD COLUMN ${name} ${type}`);
  // A provider request interrupted by a restart must be reconciled by admin, never sent twice.
  db.prepare("UPDATE direct_purchases SET state='review',error='Proses provider terputus saat restart; periksa order SMSCode sebelum menyelesaikan tagihan.' WHERE state='processing'").run();
  let notifier;const notifying=new Set();
  const get=(id,userId)=>db.prepare('SELECT * FROM direct_purchases WHERE invoice_id=? AND discord_id=?').get(id,userId);
  async function notify(row) {
    if(!notifier || row.notified || notifying.has(row.invoice_id) || !['fulfilled','refunded','review'].includes(row.state))return;
    notifying.add(row.invoice_id);
    try {await notifier(row);db.prepare('UPDATE direct_purchases SET notified=1 WHERE invoice_id=?').run(row.invoice_id);}catch { /* Buyer can retrieve the order through history when DMs are closed. */ }finally{notifying.delete(row.invoice_id);}
  }
  function refund(row,reason) {
    db.transaction(()=>{
      const updated=db.prepare("UPDATE direct_purchases SET state='refunded',error=? WHERE invoice_id=? AND state='processing'").run(reason,row.invoice_id);
      if(updated.changes)db.prepare('INSERT INTO users(discord_id,balance) VALUES(?,?) ON CONFLICT(discord_id) DO UPDATE SET balance=balance+excluded.balance').run(row.discord_id,row.amount);
    })();
  }
  async function fulfill(payment) {
    const trusted=payments.get(payment.order_id,payment.discord_id);
    const row=get(payment.order_id,payment.discord_id);
    if(!row || !trusted?.credited || trusted.purpose!=='purchase' || trusted.amount!==row.amount)throw new Error('Pembayaran pembelian belum terverifikasi.');
    if(row.state==='pending'&&['refund','partial_refund','REFUNDED'].includes(trusted.provider_status))throw new Error('Refund gateway terdeteksi. Hubungi admin untuk pencocokan pembayaran; pembelian provider belum diproses.');
    if(row.state!=='pending'){await notify(row);return row;}
    const claim=db.prepare("UPDATE direct_purchases SET state='processing' WHERE invoice_id=? AND state='pending'").run(row.invoice_id);
    if(!claim.changes)return get(row.invoice_id,row.discord_id);
    let products;
    try {const filters={platform_id:row.platform_id,country_id:row.country_id};if(row.operator_id!=null)filters.operator_id=String(row.operator_id);products=await smsCatalogProducts(filters);if(!Array.isArray(products.data))throw new Error('Katalog tidak valid');}
    catch {db.prepare("UPDATE direct_purchases SET state='pending',error='Menunggu katalog provider' WHERE invoice_id=?").run(row.invoice_id);return get(row.invoice_id,row.discord_id);}
    const product=products.data.find(p=>Number(p.id)===row.product_id && (p.operator_id==null?null:String(p.operator_id))===(row.operator_id==null?null:String(row.operator_id)));
    if(!product || !product.active || Number(product.available)<=0 || Number(product.price?.canonical_amount ?? product.price)!==row.provider_amount) {
      refund(row,'Produk habis/nonaktif atau harga provider berubah. Pembayaran dikembalikan ke saldo bot.');
    } else {
      try {
        const result=await smsCreateOrder(row.product_id,{idempotencyKey:row.invoice_id});const order=result.data?.orders?.[0];
        if(!order?.id || !/^\d+$/.test(String(order.id)) || !Number.isSafeInteger(Number(order.id)) || Number(order.id)<=0)throw new Error('Order provider belum terkonfirmasi.');
        db.prepare('UPDATE direct_purchases SET provider_order_id=? WHERE invoice_id=?').run(String(order.id),row.invoice_id);
        if(db.prepare('SELECT id FROM orders WHERE provider_order_id=?').get(String(order.id)))throw Error('ID order provider sudah tercatat; jangan membatalkan order transaksi sebelumnya.');
        const cost=Number(order.amount?.canonical_amount ?? order.amount);
        if(cost!==row.provider_amount) {
          await smsCancel(order.id);refund(row,'Harga provider berubah. Order dibatalkan dan pembayaran dikembalikan ke saldo bot.');
        } else {
          db.transaction(()=>{
            if(db.prepare('SELECT id FROM orders WHERE provider_order_id=?').get(String(order.id)))throw Error('ID order provider duplikat.');
            db.prepare('INSERT INTO orders(discord_id,product_id,provider_order_id,phone,amount,provider_amount,status) VALUES(?,?,?,?,?,?,?)').run(row.discord_id,row.product_id,String(order.id),order.phone_number,row.amount,cost,order.status || 'ACTIVE');
            db.prepare('UPDATE orders SET voucher_code=?,discount_amount=?,original_amount=?,platform_id=?,country_id=?,operator_id=?,product_name=? WHERE provider_order_id=? AND discord_id=?').run(row.voucher_code || null,row.discount_amount || 0,row.original_amount ?? row.amount,row.platform_id,row.country_id,row.operator_id,row.name,String(order.id),row.discord_id);
            db.prepare("UPDATE direct_purchases SET state='fulfilled',error=NULL WHERE invoice_id=? AND state='processing'").run(row.invoice_id);
          })();
        }
      } catch {
        db.prepare("UPDATE direct_purchases SET state='review',error='Pembayaran diterima, tetapi hasil order provider perlu diperiksa admin. Jangan membayar ulang.' WHERE invoice_id=?").run(row.invoice_id);
      }
    }
    const updated=get(row.invoice_id,row.discord_id);await notify(updated);return updated;
  }
  async function create(userId,token,customer={}) {
    assertOpen();
    if(!payments.configured)throw new Error('QRIS belum aktif. Admin perlu mengisi konfigurasi pembayaran.');
    const previous=db.prepare('SELECT * FROM direct_purchases WHERE quote_token=? AND discord_id=?').get(token,userId);
    if(previous)return {purchase:previous,payment:payments.get(previous.invoice_id,userId)};
    payments.assertCanCreate?.(userId);
    const q=commerce.checkout(userId,token);
    checkPurchase('otp',userId,q.amount);
    require('./payments').parseCustomerEmail(customer.email);
    if(q.amount<1000 || q.amount>1000000)throw new Error('Harga produk di luar batas QRIS 1.000–1.000.000 IDR. Gunakan saldo bot untuk harga di bawah 1.000 IDR.');
    const invoiceId='maboyy-buy-'+randomUUID();
    db.transaction(()=>{
    commerce.claimCoupon?.(userId,q,'invoice:'+invoiceId,invoiceId);
    db.prepare('INSERT INTO direct_purchases(invoice_id,quote_token,discord_id,product_id,platform_id,country_id,name,provider_amount,amount,operator_id) VALUES(?,?,?,?,?,?,?,?,?,?)')
      .run(invoiceId,token,userId,q.productId,String(q.platformId),String(q.countryId),q.name,q.providerAmount,q.amount,q.operatorId ?? null);
    db.prepare('UPDATE direct_purchases SET voucher_code=?,discount_amount=?,original_amount=? WHERE invoice_id=?').run(q.coupon || null,q.discount || 0,q.originalAmount ?? q.amount,invoiceId);
    })();
    commerce.checkout(userId,token,true);
    try {const payment=await payments.create(userId,q.amount,{...customer,purpose:'purchase',orderId:invoiceId});return {purchase:get(invoiceId,userId),payment};}
    catch {throw new Error('Tagihan '+invoiceId+' belum menampilkan QR. Hubungi admin untuk memeriksa Riwayat QRIS Beli sebelum membuat tagihan lain.');}
  }
  async function refresh(id,userId) {
    const row=get(id,userId);if(!row)throw new Error('Tagihan tidak ditemukan.');
    await payments.refresh(id,userId);return get(id,userId);
  }
  let polling=false;
  async function poll() {
    if(polling || !(payments.canPoll ?? payments.configured))return;polling=true;
    try {
      const rows=db.prepare("SELECT d.* FROM direct_purchases d JOIN topups t ON t.order_id=d.invoice_id WHERE d.state='pending' AND t.gateway IN ('tripay','midtrans','doku') AND t.status IN ('creating','pending','settlement') ORDER BY COALESCE(d.polled_at,'') ASC LIMIT 5").all();
      for(const r of rows){db.prepare('UPDATE direct_purchases SET polled_at=CURRENT_TIMESTAMP WHERE invoice_id=?').run(r.invoice_id);try{await refresh(r.invoice_id,r.discord_id);}catch {}}
      for(const r of db.prepare("SELECT * FROM direct_purchases WHERE notified=0 AND state IN ('fulfilled','refunded','review') LIMIT 5").all())await notify(r);
    } finally {polling=false;}
  }
  return {create,refresh,fulfill,get,poll,setNotifier:fn=>notifier=fn,
    order:row=>row.provider_order_id?db.prepare('SELECT * FROM orders WHERE provider_order_id=? AND discord_id=?').get(row.provider_order_id,row.discord_id):null,
    recent:userId=>db.prepare('SELECT * FROM direct_purchases WHERE discord_id=? ORDER BY created_at DESC,rowid DESC LIMIT 5').all(userId)};
}
function createDirectHandler({discord,direct,payments,language=()=>'id',otpPanel=null}) {
  const {ActionRowBuilder,ButtonBuilder,ButtonStyle,EmbedBuilder,ModalBuilder,TextInputBuilder,TextInputStyle}=discord;
  const money=v=>Number(v).toLocaleString('id-ID')+' IDR';
  const t=(user,id,en)=>language(user)==='en'?en:id;
  function status(row) {const p=statusBody(row);return {...p,content:`${t(row.discord_id,'Pembeli: ','Customer: ')}${buyerLabel(row.discord_id)}\n\n${p.content}`};}
  function statusBody(row) {
    const order=direct.order(row),user=row.discord_id;
    if(row.state==='fulfilled' && order?.refunded)return {content:t(user,`Pesanan ${order.provider_order_id} dibatalkan. ${money(order.amount)} sudah dikembalikan ke saldo bot.`,`Order ${order.provider_order_id} cancelled. ${money(order.amount)} has been refunded to your store balance.`),components:[]};
    if(row.state==='fulfilled' && order && otpPanel){const p=otpPanel(order.provider_order_id,user);return {...p,content:t(user,'✅ Pembayaran diterima • '+row.name+' • '+money(row.amount),'✅ Payment received • '+row.name+' • '+money(row.amount))+'\n\n'+p.content};}
    if(row.state==='fulfilled' && order)return {content:t(user,`✅ Pembayaran diterima dan pesanan berhasil.\nProduk: **${row.name}**\nHarga: **${money(row.amount)}**\nNomor: **${order.phone}**\nOrder: ${order.provider_order_id}`,`✅ Payment received and order created.\nProduct: **${row.name}**\nPrice: **${money(row.amount)}**\nPhone: **${order.phone}**\nOrder: ${order.provider_order_id}`),components:[new ActionRowBuilder().addComponents(
      new ButtonBuilder().setCustomId('check_otp:'+order.provider_order_id).setLabel('Cek OTP').setStyle(ButtonStyle.Success),
      new ButtonBuilder().setCustomId('cancel_order:'+order.provider_order_id).setLabel('Batalkan').setStyle(ButtonStyle.Danger))]};
    if(row.state==='refunded')return {content:t(user,`Pembelian tidak dapat dilanjutkan. **${money(row.amount)} dikembalikan ke saldo bot**, bukan rekening pembayaran. ${row.error}`,`Unable to complete this purchase. **${money(row.amount)} refunded to your store balance**, not your payment account. ${row.error||''}`),components:[]};
    if(row.state==='review')return {content:t(user,`Pembayaran diterima. Admin perlu memeriksa pesanan. Jangan membayar ulang.\nTagihan: ${row.invoice_id}`,`Payment received. An admin needs to review this order. Do not pay again.\nInvoice: ${row.invoice_id}`),components:[]};
    return {content:row.state==='processing'?t(user,'Pembayaran diterima. Pesanan sedang dibuat.','Payment received. Creating your order.'):t(user,'Menunggu konfirmasi pembayaran QRIS.','Awaiting QRIS payment confirmation.'),components:[checkRow(row.invoice_id)]};
  }
  function checkRow(id){return new ActionRowBuilder().addComponents(new ButtonBuilder().setCustomId('direct_check:'+id).setLabel('Cek Pembayaran & Pesanan').setStyle(ButtonStyle.Success));}
  async function handler(i) {
    const id=String(i.customId || '');
    if(!id.startsWith('qris_buy:') && !id.startsWith('direct_email:') && !id.startsWith('direct_check:'))return false;
    if(id.startsWith('qris_buy:') && payments.active?.(i.user.id)){await i.reply({ephemeral:true,content:'Masih ada tagihan QRIS aktif. Lanjutkan tagihan sebelumnya.',components:[new ActionRowBuilder().addComponents(new ButtonBuilder().setCustomId('active_invoice').setLabel('Buka Tagihan Aktif').setStyle(ButtonStyle.Primary))]});return true;}
    if(id.startsWith('qris_buy:')) {
      if(!payments.configured){await i.reply({ephemeral:true,content:'QRIS belum dikonfigurasi oleh admin.'});return true;}
      await i.showModal(new ModalBuilder().setCustomId('direct_email:'+id.slice(9)).setTitle('Email Tagihan QRIS')
        .addComponents(new ActionRowBuilder().addComponents(new TextInputBuilder().setCustomId('email').setLabel('Alamat email untuk tagihan QRIS').setStyle(TextInputStyle.Short).setRequired(true).setMaxLength(254))));return true;
    }
    await i.deferReply({ephemeral:true});
    try {
      if(id.startsWith('direct_check:')) {
        const invoice=id.slice(13);const row=await direct.refresh(invoice,i.user.id);const payment=payments.get(invoice,i.user.id);
        const response=status(row);
        if(row.state==='pending') {
          response.content=`${t(i.user.id,'Status pembayaran: ','Payment status: ')}${payment.status}. ${payment.credited?t(i.user.id,'Pembayaran diterima; menunggu provider.','Payment received; awaiting the provider.'):['expire','expired','deny','cancel','canceled','cancelled','failure','failed','EXPIRED','FAILED'].includes(payment.status)?t(i.user.id,'Tagihan tidak aktif. Pilih produk kembali untuk membuat tagihan baru.','This invoice is inactive. Select the product again for a new invoice.'):t(i.user.id,'Menunggu pembayaran; jangan membayar tagihan lain untuk pesanan ini.','Awaiting payment; do not pay a different invoice for this order.')}`;
          if(payment.qr_url && payment.status==='pending')response.embeds=[new EmbedBuilder().setColor(0x5865F2).setTitle('QRIS Pembelian').setDescription(`Total: **${money(payment.total_charge || row.amount)}**\n${payment.production?'Pindai QRIS untuk membayar.':'MODE UJI — gunakan simulator '+(payment.gateway==='midtrans'?'Midtrans':'TriPay')+'.'}`).setImage(payment.qr_url)];
        }
        if(row.state==='pending'&&payment.checkout_url&&payment.status==='pending'){
          response.embeds=[new EmbedBuilder().setColor(0x5865F2).setTitle('QRIS Pembelian').setDescription(`Total: **${money(payment.total_charge)}**\n${require('./doku').paymentInstruction(payment)}`)];
          response.components[0].addComponents(require('./doku').paymentButton(payment,discord));
        }
        await i.editReply(response);
      }else {
        const {purchase,payment}=await direct.create(i.user.id,id.slice(13),{email:i.fields.getTextInputValue('email'),name:i.user.username});
        if(purchase.state!=='pending'){await i.editReply(status(purchase));return true;}
        if(!payment?.qr_url && !payment?.checkout_url)throw new Error('QR belum tersedia. Hubungi admin untuk memeriksa riwayat tagihan.');
        const result={embeds:[new EmbedBuilder().setColor(0x5865F2).setTitle('💳 Bayar Langsung QRIS')
          .setDescription(t(i.user.id,`Produk: **${purchase.name}**\nHarga produk: **${money(purchase.amount)}**\nBiaya QRIS pembeli: **${money(payment.fee_customer || 0)}**\nTotal bayar: **${money(payment.total_charge)}**\n${payment.production?'Pindai QRIS untuk membayar.':'MODE UJI — gunakan simulator '+(payment.gateway==='midtrans'?'Midtrans':'TriPay')+'.'}\nPesanan dibuat otomatis setelah pembayaran terkonfirmasi. Stok diperiksa setelah pembayaran; jika habis, harga produk dikembalikan ke saldo bot. Biaya QRIS tidak dikembalikan otomatis. Lihat hasil di tombol Cek Pembayaran; OTP dikirim melalui DM saat masuk.`,`Product: **${purchase.name}**\nProduct price: **${money(purchase.amount)}**\nCustomer QRIS fee: **${money(payment.fee_customer || 0)}**\nTotal to pay: **${money(payment.total_charge)}**\n${payment.production?'Scan the QRIS code to pay.':'TEST MODE — use the '+(payment.gateway==='midtrans'?'Midtrans':'TriPay')+' simulator.'}\nThe order is created after payment verification. Stock is checked after payment; if unavailable, the product price is refunded to your bot balance. QRIS fees are not refunded automatically. Use Check Payment to view the result; incoming OTPs are sent by DM.`))
          .setFooter({text:purchase.invoice_id})],components:[checkRow(purchase.invoice_id)]};
        if(payment.qr_url)result.embeds[0].setImage(payment.qr_url);
        if(payment.checkout_url){result.embeds[0].setDescription(`Produk: **${purchase.name}**\nTotal bayar: **${money(payment.total_charge)}**\n${require('./doku').paymentInstruction(payment,language(i.user.id)==='en')}\nPesanan diproses otomatis setelah pembayaran terverifikasi.`);result.components[0].addComponents(require('./doku').paymentButton(payment,discord));}
        await i.editReply(result);
      }
    }catch(e){await i.editReply({content:errorText(e,language(i.user.id)==='en'),components:[new ActionRowBuilder().addComponents(new ButtonBuilder().setCustomId('active_invoice').setLabel('Tagihan Aktif').setStyle(ButtonStyle.Secondary))]});}
    return true;
  }
  handler.status=status;
  return handler;
}
module.exports={createDirectPayments,createDirectHandler};
