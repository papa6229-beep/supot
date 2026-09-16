// '자료 기준일' 펼침 목록. data-dates 가 붙은 <details> 안에 data/dates.json 을 그린다.
// 내용은 build/prep_dates.py 가 만든다.
(function(){
  var boxes = document.querySelectorAll('details[data-dates]');
  if (!boxes.length) return;
  var v = document.currentScript && document.currentScript.src.split('v=')[1] || '';
  fetch('data/dates.json?v=' + v)
    .then(function(r){ return r.ok ? r.json() : null; })
    .then(function(d){
      if (!d) return;
      var esc = function(s){ return String(s).replace(/[&<>"]/g, function(c){ return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }); };
      var html = '<table class="dtbl"><tbody>' + d.items.map(function(it){
        return '<tr><th>' + esc(it.what) + '<small>' + esc(it.src) + '</small></th>' +
               '<td><b>' + esc(it.when) + '</b>' + (it.more ? '<small>' + esc(it.more) + '</small>' : '') + '</td></tr>';
      }).join('') + '</tbody></table>' +
      '<p class="dnote">' + esc(d.built) + ' 에 받아 정리한 고정본입니다. 원천 기관이 새 자료를 내도 자동으로 바뀌지 않습니다.</p>';
      boxes.forEach(function(b){
        var body = document.createElement('div');
        body.className = 'dbody';
        body.innerHTML = html;
        b.appendChild(body);
      });
    })
    .catch(function(){});
  // 바깥을 누르면 닫는다.
  document.addEventListener('click', function(e){
    boxes.forEach(function(b){ if (b.open && !b.contains(e.target)) b.open = false; });
  });
})();
