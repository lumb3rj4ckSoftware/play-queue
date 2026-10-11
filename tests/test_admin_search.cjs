const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const search = require('../static/name_search.js');

test('search finds leetspeak, case, accents and spelling errors', () => {
  for (const [query, steam] of [['tessa','XxT3ssaxX'],['TESSA','tessa'],['tesa','Tessa'],['Mori','Möri']]) {
    assert.ok(search.rank(query,{steam_name:steam}) > 0);
  }
  assert.equal(search.rank('tessa',{steam_name:'Marcel'}),0);
});
test('search includes Twitch/display names and numeric SteamIDs', () => {
  assert.ok(search.rank('stein',{twitch_name:'steinhq'}) > 0);
  assert.ok(search.rank('Tessa',{display_name:'Tessa ♥'}) > 0);
  assert.ok(search.rank('765611',{steam_id:'76561198012345678'}) > 0);
  assert.equal(search.rank('1234',{steam_id:'76561198000000000',steam_name:'1234'}),0);
  assert.equal(search.rank('a',{steam_name:'Tessa'}),3);
});
function ui() {
  const nodes = new Map();
  const document = {
    getElementById(id) { if(!nodes.has(id))nodes.set(id,{value:'',innerHTML:'',textContent:''});return nodes.get(id); },
    addEventListener(){},querySelectorAll(){return [];},activeElement:null
  };
  const context = vm.createContext({document,PQNameSearch:search,setInterval(){},console});
  let code=fs.readFileSync(require.resolve('../static/admin.js'),'utf8');
  code=code.replace(/fetchState\(\)\.catch\(console\.error\);\s*$/,'');
  vm.runInContext(code,context);
  return {context,document};
}
test('mapping UI uses removed recent users and preserves chosen dropdown during filtering',()=>{
  const {context,document}=ui();
  context.fixture={detected_players:[{steam_id:'2',steam_name:'XxT3ssaxX',twitch_name:'tessa',steam_accounts:[{steam_id:'2'},{steam_id:'3'}]},{steam_id:'4',steam_name:'Marcel'}],link_users:[{twitch_name:'tessa',display_name:'Tessa',status:'done',last_joined_at:'2026-10-11T05:00:00',steam_accounts:[{steam_id:'2'},{steam_id:'3'}]},{twitch_name:'old_queue_friend',display_name:'Friend',status:'done',last_joined_at:'2026-10-11T06:00:00'}],queue:[]};
  vm.runInContext('latestState=fixture; renderDetected(); detectedSelections.set("2","old_queue_friend");',context);
  document.getElementById('detectedSearch').value='tesa';
  vm.runInContext('filterDetected()',context);
  const html=document.getElementById('detectedList').innerHTML;
  assert.match(html,/value="old_queue_friend" selected/);
  assert.match(html,/2 Steam-Konten/);
  assert.doesNotMatch(html,/Marcel/);
  assert.equal(document.getElementById('detectedSearchInfo').textContent,'1 von 2 Spielern');
});
test('already linked older owner stays selected and no-match message is clear',()=>{
  const {context,document}=ui();
  context.fixture={detected_players:[{steam_id:'2',steam_name:'Tessa',twitch_name:'old_owner',display_name:'Old Owner'}],link_users:[],queue:[]};
  vm.runInContext('latestState=fixture;renderDetected()',context);
  assert.match(document.getElementById('detectedList').innerHTML,/value="old_owner" selected/);
  document.getElementById('detectedSearch').value='no_such_player';
  vm.runInContext('filterDetected()',context);
  assert.match(document.getElementById('detectedList').innerHTML,/Keine passenden Spieler gefunden/);
});
