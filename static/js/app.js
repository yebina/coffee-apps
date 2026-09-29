// 豆帳：画面の小さな動き。計算や在庫のチェックはサーバーで行う（htmx）。
(function () {
  "use strict";

  // 削除などの確認：1回目で「もう一度押すと〜」に変え、4秒以内にもう一度押したら送信する
  document.addEventListener("click", function (e) {
    const btn = e.target.closest("[data-confirm]");
    if (!btn) return;
    if (btn.dataset.armed === "1") return;
    e.preventDefault();
    btn.dataset.armed = "1";
    btn.dataset.label = btn.textContent;
    btn.textContent = btn.dataset.confirm;
    btn.classList.add("is-armed");
    setTimeout(function () {
      btn.dataset.armed = "";
      btn.textContent = btn.dataset.label;
      btn.classList.remove("is-armed");
    }, 4000);
  });

  // 絞り込みの選択肢を変えたら、すぐに表示を切り替える
  document.addEventListener("change", function (e) {
    const el = e.target.closest("[data-autosubmit]");
    if (el && el.form) el.form.submit();
  });

  // 保存したときのお知らせを、少したってから消す
  function hideToasts() {
    document.querySelectorAll("[data-toast]").forEach(function (t) {
      setTimeout(function () { t.remove(); }, 3600);
    });
  }

  // エラーがあれば、その場所まで動かす
  function scrollToAlert() {
    const alert = document.querySelector(".alert[data-scroll]");
    if (alert) alert.scrollIntoView({ block: "center" });
  }

  document.addEventListener("DOMContentLoaded", function () {
    hideToasts();
    scrollToAlert();
  });
})();
