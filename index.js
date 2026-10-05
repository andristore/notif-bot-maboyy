const {createOTPLifecycle,createOTPLifecycleHandler}=require('./otp-lifecycle');
const {createStorageHealth}=require('./storage-health');
const {createRailwayLifetime,createRailwayHandler}=require('./railway-lifetime');
const {createShopUpgrades,createShopUpgradesHandler,createBuyerGameCheckHandler}=require('./shop-upgrades');
const {protectOwnerInteraction}=require('./owner-privacy');
require("dotenv").config();
const express = require("express");
const session = require("express-session");
const Database = require("better-sqlite3");
const fs = require("node:fs");
const path = require("node:path");
const {
  Client, GatewayIntentBits, REST, Routes,
  SlashCommandBuilder, EmbedBuilder, ActionRowBuilder, ButtonBuilder, ButtonStyle,
  StringSelectMenuBuilder, StringSelectMenuOptionBuilder,
  ModalBuilder, TextInputBuilder, TextInputStyle
} = require("discord.js");

const {createBuyerProfiles,configureBuyerProfiles,rememberBuyer}=require("./buyer-profiles");
const {createLanguages}=require("./languages");
const {createShopHealth,createHealthHandler}=require("./shop-health");
const {createShopImprovements,createImprovementsHandler}=require("./shop-improvements");
const {createPremiumProducts,createPremiumProductsHandler}=require("./premium-products");
const {createManualProducts,createManualProductsHandler}=require("./manual-products");
const {createBuyerManagement,createBuyerManagementHandler}=require("./buyer-management");
const {createOrderHistory,createOrderHistoryHandler,createOrderChannel,createOrderChannelHandler}=require("./order-history");
const {createAdminHandler,configureAdminAccess}=require("./admin");
const {createPurchaseFlow}=require("./purchase-flow");
const {createPayments,createPaymentHandler}=require("./payments");
const {createPricing}=require("./pricing");
const {createCommerce}=require("./commerce");
const {createDirectPayments,createDirectHandler}=require("./direct-payments");
const {createOperations,createOperationsHandler}=require("./operations");
const {createOwnerProviderHandler}=require("./owner-provider");
const {createSMSCodeWebhook,createSMSCodeWebhookHandler}=require("./smscode-webhook");
const {createServerAccess,createServerAccessHandler}=require("./server-access");
const {createStaff,createStaffHandler}=require("./staff");
const {HOME_ID,withHome,addHomeNavigation,homeForUser,dispatchInteraction}=require("./navigation");
const {createShopTools,createShopToolsHandler}=require("./shop-tools");
const {createEfficiency,createEfficiencyHandler}=require("./efficiency");
const {createStoreFeatures,createStoreFeatureHandler,REFUND_GUIDE}=require("./store-features");
const {createDigiflazz,createDigiflazzHandler}=require("./digiflazz");
const app = express();
app.set("trust proxy",1);
const webSecurity=require("./web-security").createWebSecurity();
const databasePath = process.env.DB_PATH || (process.env.RAILWAY_VOLUME_MOUNT_PATH
  ? path.join(process.env.RAILWAY_VOLUME_MOUNT_PATH, "shop.db")
  : "shop.db");
fs.mkdirSync(path.dirname(path.resolve(databasePath)), {recursive: true});
const db = new Database(databasePath);
db.pragma("journal_mode = WAL");
const diagnostics=require("./web-security").createDiagnostics({db});

db.exec(`
CREATE TABLE IF NOT EXISTS products (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  country TEXT NOT NULL,
  service TEXT NOT NULL,
  price INTEGER NOT NULL DEFAULT 0,
  enabled INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS users (
  discord_id TEXT PRIMARY KEY,
  balance INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS orders (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  discord_id TEXT NOT NULL,
  product_id INTEGER NOT NULL,
  provider_order_id TEXT,
  phone TEXT,
  otp TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  amount INTEGER NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
`);

if (db.prepare("SELECT COUNT(*) c FROM products").get().c === 0) {
  const add = db.prepare("INSERT INTO products (name,country,service,price) VALUES (?,?,?,?)");
  add.run("Indonesia • WhatsApp", "ID", "WhatsApp", 5000);
  add.run("Indonesia • Telegram", "ID", "Telegram", 5000);
  add.run("Indonesia • SMS", "ID", "SMS", 4000);
}

const pricing=createPricing(db);
let storeFeatures,upgrades;
const checkPurchase=(...args)=>upgrades?.checkPurchase(...args);
const assertStoreOpen=()=>storeFeatures?.assertOpen();
const otpLifecycle=createOTPLifecycle({db,fetchOrder:smsOrder,resendOrder:id=>smscode("/orders/resend",{method:"POST",body:JSON.stringify({id:Number(id)})})});
const commerce=createCommerce({db,pricing,smsCreateOrder,smsCancel,assertOpen:assertStoreOpen,checkPurchase});
app.use(express.json({verify:(req,res,buf)=>{req.rawBody=Buffer.from(buf);}}));
let direct,manualProducts;
const payments=createPayments({diagnostics,db,onSettled:payment=>payment.order_id.startsWith('manual-buy-')?manualProducts.fulfillPayment(payment):direct.fulfill(payment)});
commerce.setOTPPolicy(otpLifecycle);
direct=createDirectPayments({db,payments,commerce,smsCatalogProducts,smsCreateOrder,smsCancel,assertOpen:assertStoreOpen,checkPurchase});
payments.mount(app);
const directPoll=setInterval(()=>direct.poll().catch(console.error),30000);
directPoll.unref();
app.use(express.urlencoded({extended:true}));
app.use(session({
  secret: webSecurity.sessionSecret,
  resave: false, saveUninitialized: false,
  cookie: { httpOnly: true, sameSite: "lax", secure: webSecurity.secure, maxAge: 3600000 }
}));
// Cover every authenticated dashboard mutation, including order and balance endpoints.
app.use("/api",webSecurity.originGuard);
require("./public-store").mountPublicStore(app);
app.use(express.static("public"));
// The repository keeps its dashboard at the root, outside public/.
app.get('/',(req,res)=>res.sendFile(path.join(__dirname,'index.html')));

function admin(req,res,next){
  if(webSecurity.enabled&&req.session.admin) return next();
  res.status(401).json({error:"Unauthorized"});
}

async function smscode(path, options={}) {
  try {
  const base = (process.env.SMSCODE_API_BASE_URL || "https://api.smscode.gg/v1").replace(/\/$/,"");
  if(!process.env.SMSCODE_API_TOKEN) throw new Error("SMSCODE_API_TOKEN belum diisi");
  const headers = {
    "Content-Type":"application/json",
    "Authorization":`Bearer ${process.env.SMSCODE_API_TOKEN}`,
    ...(options.headers||{})
  };
  const r = await fetch(base + path, {...options, headers, signal: options.signal || AbortSignal.timeout(15_000)});
  const body = await r.text();
  let data; try { data = JSON.parse(body); } catch { data = {success:false,error:{message:body}}; }
  if(!r.ok || data.success === false) {
    throw new Error(data?.error?.message || `SMSCode HTTP ${r.status}`);
  }
  return data;
  }catch(e){diagnostics.record("provider","FAILED","smscode");throw e;}
}

function uuidKey(){ return `${Date.now()}-${Math.random().toString(16).slice(2)}`; }

const CATALOG_CACHE_MS = 60_000;
const catalogCache = new Map();
const catalogLoading = new Map();

async function smsCatalogProducts(filters={}, {fresh=false}={}){
  const query=['platform_id','country_id','operator_id'].filter(key=>filters[key]!=null)
    .map(key=>`${key}=${encodeURIComponent(filters[key])}`).join('&');
  const cached=catalogCache.get(query);
  if(!fresh && cached && Date.now() < cached.expiresAt) return cached.result;
  const loadingKey=fresh?query+'|fresh':query;
  if(catalogLoading.has(loadingKey)) return catalogLoading.get(loadingKey);
  const loading = (async()=>{
    const products = new Map();
    const limit = 1000;
    for(let page=1; ; page++){
      const result = await smscode(`/catalog/products?limit=${limit}&page=${page}&sort=name_asc${query?"&"+query:""}`);
      if(!Array.isArray(result.data)) throw new Error("Format katalog SMSCode tidak valid.");
      const rows = result.data;
      if(!rows.length) break;
      const before = products.size;
      for(const product of rows){
        if(product.id == null) throw new Error("Produk SMSCode tidak memiliki ID.");
        products.set(String(product.id), product);
      }
      if(products.size === before) throw new Error("SMSCode mengulang halaman katalog; coba lagi nanti.");
      const pageLimit = Number(result.meta?.limit) || limit;
      if(rows.length < pageLimit) break;
    }
    const result = {data: [...products.values()]};
    for(const [key,entry] of catalogCache) if(entry.expiresAt<=Date.now())catalogCache.delete(key);
    catalogCache.set(query,{result, expiresAt: Date.now() + CATALOG_CACHE_MS});
    return result;
  })();
  catalogLoading.set(loadingKey,loading);
  try { return await loading; }
  finally { catalogLoading.delete(loadingKey); }
}

function catalogPage(products, requestedPage=0){
  const pageCount = Math.max(1, Math.ceil(products.length / 25));
  const page = Math.min(Math.max(Number.isSafeInteger(requestedPage) ? requestedPage : 0, 0), pageCount-1);
  return {page, pageCount, products: products.slice(page*25, (page+1)*25)};
}

function productAvailable(p){ return Boolean(p.active) && Number(p.available)>0; }

async function smsCreateOrder(productId,{idempotencyKey=uuidKey()}={}){
  const result=await smscode("/orders/create", {
    method:"POST",
    headers:{"Idempotency-Key":idempotencyKey},
    body:JSON.stringify({product_id:Number(productId), quantity:1})
  });
  for(const order of result.data?.orders||[])otpLifecycle.observe(order);return result;
}

async function smsOrder(orderId){
  const r=await smscode(`/orders/${encodeURIComponent(orderId)}`);if(r.data&&String(r.data.id)===String(orderId))if(otpLifecycle.observe(r.data)?.revision>r.data.sms_revision)throw Error("Respons SMS lama diabaikan. Coba lagi.");return r;
}

async function smsCancel(orderId){
  const result=await smscode("/orders/cancel", {
    method:"POST",
    body:JSON.stringify({id:Number(orderId)})
  });
  if(result.data?.status!=="CANCELED"||String(result.data?.order_id)!==String(orderId))throw Error("Pembatalan belum dikonfirmasi provider; saldo belum dikembalikan.");return result;
}

app.get("/api/products",async(req,res)=>{
  try {
    const data=await smsCatalogProducts();
    const rows=data.data.map(p=>({...p,price:pricing.price(p.price?.canonical_amount ?? p.price)}));
    res.json(rows);
  } catch(e) {
    res.status(502).json({error:e.message});
  }
});

app.post("/api/admin/login",webSecurity.loginLimit,(req,res)=>{
  if(req.body.password && req.body.password === process.env.ADMIN_PASSWORD){
    return req.session.regenerate(error=>{if(error)return res.status(500).json({error:"Session login gagal dibuat."});req.session.admin=true;res.json({ok:true});});
  }
  res.status(401).json({error:"Password salah"});
});
app.post("/api/admin/logout",admin,(req,res)=>req.session.destroy(()=>res.json({ok:true})));
app.get("/api/admin/products",admin,(req,res)=>res.json(db.prepare("SELECT * FROM products ORDER BY id DESC").all()));
app.post("/api/admin/products",admin,(req,res)=>{
  let product;try{product=require('./admin').parseDashboardProduct(req.body);}catch(e){return res.status(400).json({error:e.message});}
  const {name,country,service,price,enabled}=product;
  const x=db.prepare("INSERT INTO products(name,country,service,price,enabled) VALUES(?,?,?,?,?)")
    .run(name,country,service,Number(price),enabled?1:0);
  res.json({id:x.lastInsertRowid});
});
app.patch("/api/admin/products/:id",admin,(req,res)=>{
  const p=db.prepare("SELECT * FROM products WHERE id=?").get(req.params.id);
  if(!p) return res.status(404).json({error:"Produk tidak ditemukan"});
  let product;try{product=require('./admin').parseDashboardProduct(req.body,p);}catch(e){return res.status(400).json({error:e.message});}
  const {name,country,service,price,enabled}=product;
  db.prepare("UPDATE products SET name=?,country=?,service=?,price=?,enabled=? WHERE id=?")
    .run(name,country,service,price,enabled,p.id);
  res.json({ok:true});
});

app.get("/api/admin/health",admin,async(req,res)=>{
  try {
    const bal=await smscode("/balance");
    res.json({ok:true,provider:"SMSCode",balance:bal.data});
  } catch(e){ res.json({ok:true,provider:"SMSCode",connected:false,error:e.message}); }
});

app.post("/api/order",admin,async(req,res)=>{
  const {discordId,productId}=req.body;
  if(!discordId||!productId)return res.status(400).json({error:"discordId dan productId wajib"});
  try {
    const catalog=await smsCatalogProducts();
    const p=catalog.data.find(p=>Number(p.id)===Number(productId));
    if(!p || !productAvailable(p))return res.status(400).json({error:"Produk tidak tersedia"});
    const q=commerce.quote(String(discordId),p);
    const {order,amount}=await commerce.buy(String(discordId),q.token);
    res.json({ok:true,orderId:order.id,phone:order.phone_number,amount,status:order.status});
  }catch(e){res.status(502).json({error:e.message});}
});

app.get("/api/order/:id",admin, async(req,res)=>{
  const order=db.prepare("SELECT * FROM orders WHERE provider_order_id=?").get(req.params.id);
  if(!order) return res.status(404).json({error:"Order tidak ditemukan"});
  try {
    const state=await otpLifecycle.refresh(req.params.id,order.discord_id);
    res.json({ok:true,status:state.order.status,otp:state.order.otp,phone:state.order.phone,expiresAt:new Date(state.expires).toISOString()});
  } catch(e){res.status(502).json({error:e.message});}
});

app.post("/api/order/:id/cancel",admin,async(req,res)=>{
  const order=db.prepare("SELECT * FROM orders WHERE provider_order_id=?").get(req.params.id);
  if(!order)return res.status(404).json({error:"Order tidak ditemukan"});
  try {const refund=await commerce.cancel(req.params.id,order.discord_id);res.json({ok:true,status:"CANCELED",refund});}
  catch(e){res.status(502).json({error:e.message});}
});

app.post("/api/discord/balance",admin, (req,res)=>{
  const id=String(req.body.discordId||"");
  if(!id) return res.status(400).json({error:"discordId wajib"});
  db.prepare("INSERT INTO users(discord_id,balance) VALUES(?,0) ON CONFLICT(discord_id) DO NOTHING").run(id);
  res.json(db.prepare("SELECT balance FROM users WHERE discord_id=?").get(id));
});

const client = new Client({intents:[GatewayIntentBits.Guilds]});
const sendDiscordDM=async(id,content)=>{if(!client.isReady())throw new Error('Discord belum siap');const user=await client.users.fetch(id);await user.send({content,allowedMentions:{parse:[]}});};
const staff=createStaff({db});upgrades=createShopUpgrades({db,staff,sendDM:sendDiscordDM,resolveUser:id=>client.users.fetch(id)});staff.canRoute=(user,id)=>upgrades.canRoute(user,id);configureAdminAccess(staff);commerce.setOwnerAccess(id=>staff.isOwner(id));
const railwayLifetime=createRailwayLifetime({db,staff,sendDM:sendDiscordDM});
const languages=createLanguages({db,staff});
storeFeatures=createStoreFeatures({db,staff,sendDM:sendDiscordDM,resolveInfoChannel:async id=>{const c=await client.channels.fetch(id);if(!c)return null;const bits=require('discord.js').PermissionFlagsBits,p=c.permissionsFor(client.user);return {id:c.id,guildId:c.guildId,type:c.type,canInfo:!!p&&p.has(bits.ViewChannel)&&p.has(bits.SendMessages),send:payload=>c.send(payload)};}});
manualProducts=createManualProducts({diagnostics,db,staff,payments,sendAdminDM:sendDiscordDM,maintenance:()=>storeFeatures.maintenance(),checkPurchase,audit:(id,action)=>{if(!staff.isAdmin(id))throw Error('Akses ditolak.');db.prepare('INSERT INTO shop_admin_audit(admin_id,action) VALUES(?,?)').run(id,action);}});
const digiflazz=createDigiflazz({db,pricing,assertOpen:assertStoreOpen,checkPurchase,nicknameChecker:upgrades.nickname,needsNickname:upgrades.needsNickname,nicknameNeedsServer:upgrades.nicknameNeedsServer,observeCatalog:upgrades.observeCatalog,staff,sendDM:sendDiscordDM,audit:(id,action)=>{if(!staff.isAdmin(id))throw Error('Akses ditolak.');db.prepare('INSERT INTO shop_admin_audit(admin_id,action) VALUES(?,?)').run(id,action);}});
digiflazz.mount(app);
const serverAccess=createServerAccess({db,sendDM:sendDiscordDM,staff,isMember:async(guildId,userId)=>{const guild=client.guilds.cache.get(guildId);if(!guild)return false;const member=await guild.members.fetch({user:userId,force:true});return !!member;}});
const releaseInfo=require('./release-info').createReleaseInfo({db,staff,release:require('./release.json'),resolveChannel:async id=>{
  const c=await client.channels.fetch(id);if(!c||c.type!==0)return null;
  const bits=require('discord.js').PermissionFlagsBits,p=c.permissionsFor(client.user);
  return {type:c.type,approved:serverAccess.get(c.guildId)?.status==='approved',canSend:!!p&&[bits.ViewChannel,bits.SendMessages,bits.EmbedLinks,bits.ReadMessageHistory].every(bit=>p.has(bit)),send:payload=>c.send(payload),findMessage:async(marker,messageId)=>{
    const match=m=>m.author?.id===client.user.id&&m.embeds?.some(e=>e.footer?.text===marker);
    if(messageId){const m=await c.messages.fetch(messageId);return match(m)?m.id:null;}
    const messages=await c.messages.fetch({limit:100});return messages.find(match)?.id||null;
  }};
}});
const improvements=createShopImprovements({db,staff,access:serverAccess,resolveChannel:id=>client.channels.fetch(id)});
const operations=createOperations({db,smscode,smsOrder,smsCancel,payments,
  sendDM:(id,body,meta)=>meta?improvements.send(meta.kind,meta.ref,id,()=>sendDiscordDM(id,body)):sendDiscordDM(id,body),language:id=>languages.get(id),staff});
const smsWebhook=createSMSCodeWebhook({diagnostics,db,operations});smsWebhook.mount(app);
const smsWebhookPoll=setInterval(()=>smsWebhook.drain().catch(console.error),15000);smsWebhookPoll.unref();
smsWebhook.drain().catch(console.error);
client.on('guildCreate',guild=>serverAccess.register(guild).catch(console.error));
client.on('guildDelete',guild=>{if(!guild.unavailable)serverAccess.removed(guild.id);});
client.once('clientReady',async()=>{for(const guild of client.guilds.cache.values())try{await serverAccess.register(guild);}catch(e){console.error(e);}});
async function startDiscord(){
  if(!process.env.DISCORD_TOKEN) return console.log("DISCORD_TOKEN belum diisi; bot tidak dijalankan.");
  const commands=[
    new SlashCommandBuilder().setName("shop").setDescription("Buka panel toko OTP"),
    new SlashCommandBuilder().setName("admin").setDescription("Buka panel admin toko"),
    new SlashCommandBuilder().setName("ping").setDescription("Cek respons dan koneksi bot (admin)")
  ].map(x=>x.toJSON());
  const rest=new REST({version:"10"}).setToken(process.env.DISCORD_TOKEN);
  // Resolve the application from the authenticated bot instead of silently
  // skipping registration when DISCORD_CLIENT_ID is missing or stale.
  try{
    const application=await rest.get('/oauth2/applications/@me');
    if(!/^\d{17,20}$/.test(String(application?.id||'')))throw Error('Application ID tidak valid');
    if(process.env.DISCORD_CLIENT_ID&&process.env.DISCORD_CLIENT_ID.trim()!==application.id)console.warn('DISCORD_CLIENT_ID tidak sesuai token; memakai Application ID bot yang terautentikasi.');
    const registered=await rest.put(Routes.applicationCommands(application.id),{body:commands});
    if(!Array.isArray(registered)||!commands.every(c=>registered.some(r=>r.name===c.name)))throw Error('Discord belum mengonfirmasi semua command');
    console.log('Command Discord berhasil didaftarkan: /shop, /admin, /ping');
  }catch(e){
    console.error('Pendaftaran command Discord gagal. Kode:',e.code||e.status||'tidak diketahui','Periksa token, koneksi dan izin aplikasi Discord.');
    throw Error('Bot belum dapat mendaftarkan /shop, /admin dan /ping. Lihat log pendaftaran command.');
  }
  function money(n){ return `${Number(n||0).toLocaleString("id-ID")} IDR`; }

  async function getBalance(id){
    db.prepare("INSERT INTO users(discord_id,balance) VALUES(?,0) ON CONFLICT(discord_id) DO NOTHING").run(id);
    return db.prepare("SELECT balance FROM users WHERE discord_id=?").get(id).balance;
  }

  function shopEmbed(title="Hi, Belanja Produk Digital Yukk"){
    return new EmbedBuilder()
      .setColor(0x5865F2)
      .setTitle(`🛍️ ${title}`)
      .setDescription("Selamat datang di Produk Digital by Maboyy")
      .setFooter({text:"est. 2020 — Bot Otomatis 24/7"});
  }

  function mainRow(){
    return [new ActionRowBuilder().addComponents(
      new ButtonBuilder().setCustomId("shop_products").setLabel("Beli OTP").setEmoji("🛒").setStyle(ButtonStyle.Primary),
      new ButtonBuilder().setCustomId("shop_games").setLabel("Topup Game").setEmoji("🎮").setStyle(ButtonStyle.Primary),
      new ButtonBuilder().setCustomId("shop_manual_products").setLabel("Produk Lainnya").setEmoji("📦").setStyle(ButtonStyle.Primary)
    ),new ActionRowBuilder().addComponents(
      new ButtonBuilder().setCustomId("shop_balance").setLabel("Saldo").setEmoji("💰").setStyle(ButtonStyle.Success),
      new ButtonBuilder().setCustomId("shop_orders").setLabel("Pesanan").setEmoji("📦").setStyle(ButtonStyle.Secondary),
      new ButtonBuilder().setCustomId("shop_topup").setLabel("Isi Saldo").setEmoji("💳").setStyle(ButtonStyle.Primary),
      new ButtonBuilder().setCustomId("buyer_game_check_menu").setLabel("Cek Akun Game").setEmoji("🔎").setStyle(ButtonStyle.Primary)
    ),new ActionRowBuilder().addComponents(
      new ButtonBuilder().setCustomId("shop_help").setLabel("Bantuan").setEmoji("❓").setStyle(ButtonStyle.Secondary),
      new ButtonBuilder().setCustomId("shop_language:shop").setLabel("Bahasa / Language").setEmoji("🌐").setStyle(ButtonStyle.Primary)
    )];
  }

  const efficiency=createEfficiency({db,staff});
  const toolkit=createShopTools({db,staff,language:id=>languages.get(id),payments,smsCatalogProducts,pricing,sendDM:sendDiscordDM,openBackup:file=>new Database(file,{readonly:true,fileMustExist:true}),backupDir:process.env.BACKUP_DIR || path.join(path.dirname(path.resolve(databasePath)),"backups")});
  const shopHealth=createShopHealth({diagnostics,db,staff,payments,language:id=>languages.get(id),products:manualProducts,sendDM:sendDiscordDM,inspectChannel:async(guildId,channelId)=>{const c=await client.channels.fetch(channelId),access=serverAccess.get(guildId);if(!access||access.status!=='approved')return 'Server belum disetujui.';if(access.channel_id&&access.channel_id!==channelId)return 'Buka pemeriksaan dari channel toko yang diizinkan.';if(!c||c.guildId!==guildId||c.type!==0)return 'Gunakan channel teks server.';const bits=require("discord.js").PermissionFlagsBits,p=c.permissionsFor(client.user);return p&&p.has(bits.ViewChannel)&&p.has(bits.SendMessages)&&p.has(bits.EmbedLinks)?'Izin lihat/kirim/embed tersedia.':'Izin lihat/kirim/embed belum lengkap.';}});
  const handleBuyerGameCheck=createBuyerGameCheckHandler({discord:require("discord.js"),model:upgrades});
  const handleOTPLifecycle=createOTPLifecycleHandler({discord:require("discord.js"),model:otpLifecycle,commerce});
  const handleUpgrades=createShopUpgradesHandler({discord:require("discord.js"),model:upgrades,staff,tools:toolkit,digiflazz,smscode,efficiency});
  const upgradeAlertsPoll=setInterval(()=>upgrades.pollAlerts().catch(console.error),60000);upgradeAlertsPoll.unref();upgrades.pollAlerts().catch(console.error);
  const handleHealth=createHealthHandler({discord:require("discord.js"),model:shopHealth,staff});
  const handleQrisControl=require('./qris-control').createQrisControlHandler({discord:require('discord.js'),payments,staff});
  const qrisAlertPoll=setInterval(()=>payments.control.pollAlerts(payments,staff,sendDiscordDM).catch(()=>console.error('Peringatan QRIS belum terkirim.')),60000);qrisAlertPoll.unref();
  const buyerManagement=createBuyerManagement({db,staff});
  const handleBuyerManagement=createBuyerManagementHandler({discord:require("discord.js"),model:buyerManagement,staff});
  const buyerArchivePoll=setInterval(()=>{try{buyerManagement.sweep();}catch(e){console.error(e);}},3600000);buyerArchivePoll.unref();buyerManagement.sweep();
  const buyerProfiles=createBuyerProfiles({db,resolveUser:id=>client.users.fetch(id)});
  configureBuyerProfiles(buyerProfiles);
  commerce.setCoupons(toolkit.coupons);
  const handleTools=createShopToolsHandler({discord:require("discord.js"),tools:toolkit,staff,commerce});
  const handleEfficiency=createEfficiencyHandler({discord:require("discord.js"),model:efficiency,commerce,payments,features:storeFeatures,staff,smscode,operations,otpPanel:handleOTPLifecycle.panel});
  const handleRailway=createRailwayHandler({discord:require("discord.js"),staff,model:railwayLifetime});
  const railwayPoll=setInterval(()=>railwayLifetime.poll().catch(console.error),60000);railwayPoll.unref();railwayLifetime.poll().catch(console.error);
  const measureStorage=createStorageHealth({databasePath,backupDir:process.env.BACKUP_DIR || path.join(path.dirname(path.resolve(databasePath)),"backups"),volumePath:process.env.RAILWAY_VOLUME_MOUNT_PATH,appDir:__dirname});
  const handleAdmin=createAdminHandler({discord:require("discord.js"),db,smscode,pricing,staff,resolveUser:id=>client.users.fetch(id),measureHealth:async()=>{const started=process.hrtime.bigint();db.prepare("SELECT 1").get();return {discord:client.ws.ping,database:Number(process.hrtime.bigint()-started)/1000000,ram:process.memoryUsage().rss/1024/1024,storage:await measureStorage(),railway:await railwayLifetime.refresh()};},audit:toolkit.audit});
  const premiumProducts=createPremiumProducts({db,staff,language:id=>languages.get(id),products:manualProducts,sendDM:async(id,payload)=>{const user=await client.users.fetch(id);await user.send(languages.translate(withHome(payload,homeForUser(staff,id)),id,'delivery'));}});
  const handlePremiumProducts=createPremiumProductsHandler({discord:require("discord.js"),language:id=>languages.get(id),model:premiumProducts,products:manualProducts,staff});
  const handleManualProducts=createManualProductsHandler({discord:require("discord.js"),model:manualProducts,staff,premium:premiumProducts,language:id=>languages.get(id),sendDM:async(id,payload,order)=>{const send=async()=>{const user=await client.users.fetch(id);await user.send(languages.translate(withHome(payload,homeForUser(staff,id)),id,'delivery'));};if(order)await improvements.send("digital",order.id,id,send);else await send();}});
  const handleImprovements=createImprovementsHandler({discord:require("discord.js"),model:improvements,products:manualProducts,operations,staff});
  const handleOrderHistory=createOrderHistoryHandler({discord:require("discord.js"),model:createOrderHistory({db}),payments,premium:premiumProducts,language:id=>languages.get(id)});
  const orderChannel=createOrderChannel({db,staff,resolveChannel:async id=>{const c=await client.channels.fetch(id);if(!c)return null;const bits=require('discord.js').PermissionFlagsBits,p=c.permissionsFor(client.user);return {id:c.id,guildId:c.guildId,type:c.type,canReport:!!p&&p.has(bits.ViewChannel)&&p.has(bits.SendMessages)&&p.has(bits.EmbedLinks),send:payload=>c.send(payload)};},send:(c,p)=>c.send(p)});
  const handleOrderChannel=createOrderChannelHandler({discord:require('discord.js'),model:orderChannel,staff});
  const handleFlow=createPurchaseFlow({discord:require("discord.js"),smscode,smsCatalogProducts,pricing,resolveFavorite:(user,id)=>efficiency.favorite(user,id)});
  const handleProviderFlow=createPurchaseFlow({discord:require("discord.js"),smscode,smsCatalogProducts,pricing,adminView:true,isOwner:id=>staff.isOwner(id)});
  const handlePayment=createPaymentHandler({discord:require("discord.js"),language:id=>languages.get(id),payments,manualInstructions:()=>operations.settings().manual,adminIds:i=>staff.contactIds(i.guildId)});
  const handleStaff=createStaffHandler({discord:require("discord.js"),staff,resolveUser:id=>client.users.fetch(id)});
  const handleOwnerProvider=createOwnerProviderHandler({discord:require("discord.js"),staff,commerce,smscode,smsCatalogProducts,otpPanel:handleOTPLifecycle.panel});
  const handleSMSWebhook=createSMSCodeWebhookHandler({staff});
  const handleOperations=createOperationsHandler({discord:require("discord.js"),ops:operations});
  const handleReleaseInfo=require('./release-info').createReleaseInfoHandler({discord:require('discord.js'),model:releaseInfo,staff});
  const handleWalletRecovery=require('./wallet-recovery').createWalletRecoveryHandler({discord:require('discord.js'),commerce,staff,fetchOrder:smsOrder});
  const handleServerAccess=createServerAccessHandler({discord:require("discord.js"),access:serverAccess,resolveChannel:id=>client.channels.fetch(id),resolveRole:async(guildId,roleId)=>(await client.guilds.fetch(guildId)).roles.fetch(roleId)});
  const handleDirect=createDirectHandler({discord:require("discord.js"),direct,payments,language:id=>languages.get(id),otpPanel:handleOTPLifecycle.panel});
  const handleStoreFeatures=createStoreFeatureHandler({discord:require("discord.js"),features:storeFeatures,staff});
  const handleDigiflazz=createDigiflazzHandler({discord:require("discord.js"),model:digiflazz,getBalance,staff});
  direct.setNotifier(async row=>{const user=await client.users.fetch(row.discord_id);await user.send(languages.translate(withHome(handleDirect.status(row),homeForUser(staff,row.discord_id)),row.discord_id,'delivery'));});
  client.on("interactionCreate", async i=>{
    try {
      const id=i.user.id;
      languages.attach(i);
      if(await protectOwnerInteraction(i,staff))return;
      if(await serverAccess.gate(i))return;
      rememberBuyer(i.user);buyerManagement.touch(i.user.id);
      addHomeNavigation(i,staff);
      if(await languages.handle(i,()=>({embeds:[shopEmbed()],components:mainRow()})))return;
      if(await languages.onboard(i))return;
      if(i.isButton() && (i.customId===HOME_ID || i.customId==='manual_back')){
        if(i.customId===HOME_ID&&staff.isAdmin(i.user.id))return dispatchInteraction(handleAdmin,i);
        return i.reply({ephemeral:true,embeds:[shopEmbed()],components:mainRow()});
      }
      if(await dispatchInteraction(handleOTPLifecycle,i))return;
      if(await dispatchInteraction(handleWalletRecovery,i))return;
      if(await dispatchInteraction(handleReleaseInfo,i))return;
      if(await dispatchInteraction(handleBuyerGameCheck,i))return;
      if(await dispatchInteraction(handleUpgrades,i))return;
      if(i.customId==='admin_balance_save'&&!staff.isOwner(i.user.id)&&upgrades.settings().approvalThreshold>0&&Number(i.fields.getTextInputValue('amount'))>=upgrades.settings().approvalThreshold){await i.deferReply({ephemeral:true});const p=await upgrades.requestCredit(i);await i.editReply({content:'Pengajuan '+p.id+' menunggu owner di Dashboard Owner → Pengajuan Saldo. Saldo belum ditambahkan.',allowedMentions:{parse:[]}});return;}
      if(await dispatchInteraction(handleQrisControl,i))return;
      if(await dispatchInteraction(handleHealth,i))return;
      if(await dispatchInteraction(handleOrderChannel,i))return;
      if(await dispatchInteraction(handleImprovements,i))return;
      if(await dispatchInteraction(handleStoreFeatures,i))return;
      if(await dispatchInteraction(handleDigiflazz,i))return;
      if(storeFeatures.maintenance() && /^(shop_products|shop_games|df_|flow_|pick_product:|buy_again:|confirm_buy:|qris_buy:|direct_email:|favorite_open:|tool_coupon)/.test(String(i.customId || ''))){
        return i.reply({ephemeral:true,content:'🔧 Toko sedang maintenance. Pembelian baru dihentikan sementara. Pesanan, OTP, dan tagihan sebelumnya tetap tersedia.'});
      }
      if(await dispatchInteraction(handleTools,i))return;
      if(await dispatchInteraction(handlePremiumProducts,i))return;
      if(await dispatchInteraction(handleOrderHistory,i))return;
      if(await dispatchInteraction(handleEfficiency,i))return;
      if(await dispatchInteraction(handleStaff,i))return;
      if(await dispatchInteraction(handleServerAccess,i))return;
      if(await dispatchInteraction(handleOwnerProvider,i))return;
      if(await dispatchInteraction(handleSMSWebhook,i))return;
      if(await dispatchInteraction(handleOperations,i)) return;
      if(await dispatchInteraction(handleManualProducts,i)) return;
      if(await dispatchInteraction(handleBuyerManagement,i))return;
      if(await dispatchInteraction(handleRailway,i))return;
      if(await dispatchInteraction(handleAdmin,i)) return;
      if(await dispatchInteraction(handleProviderFlow,i)) return;
      if(await dispatchInteraction(handlePayment,i)) return;
      if(await dispatchInteraction(handleDirect,i)) return;
      if(await dispatchInteraction(handleFlow,i)) return;

      if(i.isChatInputCommand() && i.commandName==="shop"){
        return i.reply({embeds:[shopEmbed()],components:mainRow()});
      }

      if(i.isButton()){
        if(i.customId==="shop_balance"){
          const balance=await getBalance(id);
          return i.reply({
            ephemeral:true,
            embeds:[new EmbedBuilder().setColor(0x57F287).setTitle("💰 Saldo Anda").setDescription(`Saldo saat ini:\n\n# **${money(balance)}**`)]
          });
        }

        if(i.customId==="shop_guide"){
          return i.reply({ephemeral:true,embeds:[new EmbedBuilder().setColor(0x5865F2).setTitle("Panduan Pembeli Baru")
            .setDescription("1. Pilih **Beli OTP** atau **Produk Lainnya**.\n2. Baca deskripsi dan harga, lalu konfirmasi.\n3. Bayar memakai saldo toko atau QRIS jika tersedia. Isi saldo minimal **5.000 IDR**.\n4. QRIS belum terkonfirmasi? Buka **Pesanan → Invoice → Cek Pembayaran & Pesanan**. Gunakan tagihan yang sama.\n5. Produk otomatis dan OTP dikirim melalui DM. Aktifkan izin DM dari anggota server. Produk yang diproses admin mengikuti waktu pada deskripsi.\n6. Lihat hasil melalui **Pesanan → Riwayat Pesanan**. Tombol **Beli Lagi** membuka konfirmasi baru dengan harga terbaru.")],
            components:[new ActionRowBuilder().addComponents(new ButtonBuilder().setCustomId('shop_help').setLabel('Kembali').setStyle(ButtonStyle.Primary),new ButtonBuilder().setCustomId('shop_home').setLabel('Menu Awal').setStyle(ButtonStyle.Primary))]});
        }
        if(i.customId==="shop_help"){
          return i.reply({
            ephemeral:true,
            embeds:[new EmbedBuilder().setColor(0xFEE75C).setTitle("❓ Bantuan")
              .setDescription(
                "**Cara membeli OTP**\n" +
                "1. Klik **Beli OTP**\n" +
                "2. Pilih aplikasi, negara, operator, dan harga\n" +
                "3. Konfirmasi pembelian\n" +
                "4. Nomor akan diberikan\n" +
                "5. OTP dikirim melalui DM saat masuk; **Cek OTP** tetap tersedia\n\n" +
                "Jika order gagal, hubungi admin toko."
              )],components:[new ActionRowBuilder().addComponents(new ButtonBuilder().setCustomId('shop_guide').setLabel('Panduan Pembeli Baru').setStyle(ButtonStyle.Primary),new ButtonBuilder().setCustomId('shop_refund_guide').setLabel('Panduan Refund').setStyle(ButtonStyle.Secondary),new ButtonBuilder().setCustomId('tool_ticket_new').setLabel('Buat Tiket Bantuan').setStyle(ButtonStyle.Primary),new ButtonBuilder().setCustomId('tool_tickets:0').setLabel('Tiket Saya').setStyle(ButtonStyle.Primary))]
          });
        }

        if(i.customId.startsWith("confirm_buy:")){
          const token=i.customId.split(":")[1];
          await i.deferReply({ephemeral:true});
          try{
            const {order,amount}=await commerce.buy(id,token);
            const panel=handleOTPLifecycle.panel(String(order.id),id);panel.content='✅ Order berhasil • Harga: '+money(amount)+'\nOTP dikirim melalui DM saat masuk.\n\n'+panel.content;return i.editReply(panel);
          }catch(e){
            const owner=/saldo tidak cukup/i.test(e.message)?staff.contactIds(i.guildId)[0]:null;
            if(owner)return i.editReply({content:'❌ '+e.message+' Tekan Hubungi Admin untuk isi saldo melalui DM.',components:[new ActionRowBuilder().addComponents(new ButtonBuilder().setLabel('Hubungi Admin').setStyle(ButtonStyle.Link).setURL('https://discord.com/users/'+owner))]});
            return i.editReply("❌ Gagal membuat order: "+e.message);
          }
        }


      }

      if((i.isButton() && (i.customId.startsWith("pick_product:") || i.customId.startsWith('buy_again:'))) || (i.isStringSelectMenu() && i.customId==="buy_product")){
        await i.deferReply({ephemeral:true});
        const repeat=i.customId?.startsWith('buy_again:')?storeFeatures.repeat(i.customId.split(':')[1],id):null;
        const pid=Number(repeat?repeat.productId:i.isButton()?i.customId.split(":")[1]:i.values[0]);
        const parts=repeat?(repeat.platformId && repeat.countryId?['pick_product',String(pid),String(repeat.platformId),String(repeat.countryId),repeat.operatorId==null?'any':String(repeat.operatorId)]:[]):i.isButton()?i.customId.split(':'):[];
        const filters=parts.length>=4?{platform_id:parts[2],country_id:parts[3]}:{};
        if(parts[4] && parts[4]!=='any')filters.operator_id=parts[4];
        const data=await smsCatalogProducts(filters);
        const p=(data.data||[]).find(x=>Number(x.id)===pid && (parts.length<4 || ((x.operator_id==null?'any':String(x.operator_id))===(parts[4] || 'any') && String(x.platform_id)===parts[2] && String(x.country_id)===parts[3])));
        if(!p || !productAvailable(p)) return i.editReply({content:"Produk sedang tidak tersedia. Pilih layanan lain dari katalog."});
        const quote=commerce.quote(id,p);
        const price=quote.amount;
        const balance=await getBalance(id);
        const confirm=new ActionRowBuilder().addComponents(
          new ButtonBuilder().setCustomId(`confirm_buy:${quote.token}`).setLabel("Bayar Pakai Saldo").setEmoji("💰").setStyle(ButtonStyle.Success),
          new ButtonBuilder().setCustomId(`qris_buy:${quote.token}`).setLabel("Bayar Langsung QRIS").setEmoji("💳").setStyle(ButtonStyle.Primary).setDisabled(price<1000),
          new ButtonBuilder().setCustomId("shop_products").setLabel("Kembali").setEmoji("↩️").setStyle(ButtonStyle.Secondary),
          new ButtonBuilder().setCustomId('shop_refund_guide').setLabel('Panduan Refund').setStyle(ButtonStyle.Secondary)
        );
        return i.editReply({
          embeds:[new EmbedBuilder().setColor(0x5865F2).setTitle("🧾 Konfirmasi Pembelian")
            .addFields(
              {name:"Produk",value:`**${p.name}**`,inline:false},
              {name:"Harga",value:`**${money(price)}**`,inline:true},
              {name:"Saldo",value:`**${money(balance)}**`,inline:true},
              {name:"Stok",value:`**${p.available}**`,inline:true}
            )
            .setDescription("Pastikan produk dan harga terbaru sudah benar sebelum melanjutkan.\n\nRefund harga produk masuk ke saldo bot, termasuk pembayaran QRIS. Biaya QRIS tidak ikut dikembalikan. Pesanan yang sudah menerima OTP tidak dapat dibatalkan. Tekan Panduan Refund untuk detail.")],
          components:[confirm,new ActionRowBuilder().addComponents(new ButtonBuilder().setCustomId('favorite_save:'+quote.token).setLabel('Simpan Favorit').setStyle(ButtonStyle.Secondary),new ButtonBuilder().setCustomId('tool_coupon:'+quote.token).setLabel('Gunakan Voucher').setStyle(ButtonStyle.Primary))]
        });
      }
      if(!i.replied&&!i.deferred)await i.reply({ephemeral:true,content:'Menu ini sudah berubah atau tidak tersedia. Buka Menu Awal untuk melanjutkan.',allowedMentions:{parse:[]}});
    } catch(e){
      diagnostics.record("interaction","FAILED",i.id);
      console.error("Interaksi Discord gagal; referensi",i.id,"kode",Number.isInteger(e.code)?e.code:"tidak diketahui");
      try{
        if(i.deferred) await i.editReply("❌ Terjadi kesalahan.");
        else if(!i.replied) await i.reply({ephemeral:true,content:"❌ Terjadi kesalahan."});
      }catch{}
    }
  });

  await client.login(process.env.DISCORD_TOKEN);
  const pollRelease=()=>releaseInfo.poll().catch(()=>console.error('Info Update belum terkirim. Periksa pengaturan channel.'));
  const releasePoll=setInterval(pollRelease,60000);releasePoll.unref();pollRelease();
  if(digiflazz.configured())digiflazz.sync().then(n=>console.log('Katalog Digiflazz tersinkron:',n)).catch(e=>console.error('Sinkron Digiflazz gagal:',e.message));
  const digiflazzSyncMinutes=Math.max(5,Number(process.env.DIGIFLAZZ_SYNC_MINUTES)||15);
  const digiflazzSync=setInterval(()=>{if(digiflazz.configured())digiflazz.sync().catch(e=>console.error('Sinkron Digiflazz gagal:',e.message));},digiflazzSyncMinutes*60000);digiflazzSync.unref();
  const digiflazzPoll=setInterval(()=>digiflazz.poll().catch(e=>console.error('Poll Digiflazz gagal:',e.message)),30000);digiflazzPoll.unref();
  const orderChannelPoll=setInterval(()=>orderChannel.poll().catch(()=>console.error('Laporan channel pesanan gagal; periksa konfigurasi tujuan.')),30000);orderChannelPoll.unref();orderChannel.poll().catch(()=>console.error('Laporan channel pesanan gagal; periksa konfigurasi tujuan.'));
  const otpPoll=setInterval(()=>operations.pollOTP().catch(console.error),15000);otpPoll.unref();
  const lowPoll=setInterval(()=>operations.pollLow().catch(console.error),60000);lowPoll.unref();
  operations.pollOTP().catch(console.error);operations.pollLow().catch(console.error);
  const pendingPoll=setInterval(()=>toolkit.reconcile().catch(console.error),30000);pendingPoll.unref();toolkit.reconcile().catch(console.error);
  const ticketPoll=setInterval(()=>toolkit.notifyTickets().catch(console.error),30000);ticketPoll.unref();toolkit.notifyTickets().catch(console.error);
  const stockPoll=setInterval(()=>toolkit.stock().catch(console.error),60000);stockPoll.unref();toolkit.stock().catch(console.error);
  const backupPoll=setInterval(()=>toolkit.backup().catch(console.error),3600000);backupPoll.unref();toolkit.backup().catch(console.error);
  const manualPoll=setInterval(()=>storeFeatures.poll().catch(console.error),30000);manualPoll.unref();storeFeatures.poll().catch(console.error);
  const premiumPoll=setInterval(()=>premiumProducts.poll().catch(console.error),60000);premiumPoll.unref();premiumProducts.poll().catch(console.error);
  const overduePoll=setInterval(()=>shopHealth.poll().catch(console.error),60000);overduePoll.unref();shopHealth.poll().catch(console.error);
  const manualProductPoll=setInterval(()=>manualProducts.poll().catch(console.error),30000);manualProductPoll.unref();manualProducts.poll().catch(console.error);
}
startDiscord().catch(()=>{console.error('Discord gagal dimulai. Bot berhenti agar hosting dapat menjalankan ulang.');client.destroy();db.close();process.exit(1);});

app.listen(process.env.PORT||3000,()=>console.log(`Dashboard: http://localhost:${process.env.PORT||3000}`));
