
async function loadPending(){
  try{
    const res = await fetch('/api/pending_count');
    const j = await res.json();
    const el = document.getElementById('pending-count');
    if(el) el.textContent = j.pending;
    const el2 = document.getElementById('pending-count-2');
    if(el2) el2.textContent = j.pending;
  }catch(e){}
}
setInterval(loadPending, 5000);
loadPending();
