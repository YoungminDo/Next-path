/* Seller information shown wherever something is sold (전자상거래법 §10, §13): name, 대표,
   address, phone, business and mail-order registration numbers, and the two policies. */
export default function BusinessInfo() {
  return (
    <div className="bizinfo">
      <p>
        <a href="/terms">이용약관</a> · <a href="/privacy"><b>개인정보처리방침</b></a>
      </p>
      <p>
        주식회사 대시(DA-SH) · 대표 도영민 · 사업자등록번호 340-87-03755 · 통신판매업신고 제2026-서울중구-204호
        · 직업정보제공사업 신고 서울청 제2026-3호
      </p>
      <p>서울특별시 중구 세종대로 136, 3층 에스3097호(무교동, 파이낸스빌딩) · 010-9640-3724 · branden@da-sh.io</p>
    </div>
  );
}
