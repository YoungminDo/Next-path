import Link from "next/link";

import BusinessInfo from "@/components/BusinessInfo";

/* Terms of service for nextpath, including the paid cards (전자상거래법: price, withdrawal and
   refund). Every price and rule here is what the service does (docs/10 §결과 카드와 결제);
   change this page in the same commit as the code or the pricing_policy row. */
export const metadata = { title: "nextpath · 이용약관" };

const EFFECTIVE = "2026년 10월 13일";

export default function Terms() {
  return (
    <main className="policy">
      <header>
        <Link href="/" className="brand">nextpath</Link>
        <h1>이용약관</h1>
        <p className="meta">시행일 {EFFECTIVE} · 서비스 nextpath(nextpath.da-sh.io) · 운영 주식회사 대시(DA-SH)</p>
      </header>

      <h2>1. 목적</h2>
      <p>이 약관은 주식회사 대시(이하 &ldquo;회사&rdquo;)가 제공하는 nextpath(이하 &ldquo;서비스&rdquo;)의 이용 조건과 절차,
        회사와 이용자의 권리·의무를 정합니다.</p>

      <h2>2. 서비스 내용</h2>
      <ul>
        <li>입력한 학교·전공·학번·직무와 비슷한 사람들이 어떤 진로를 택했는지 묶음 통계로 보여드립니다.</li>
        <li>통계는 개인을 알아볼 수 없도록 5명 미만 묶음을 숨기며, 진로 결정을 위한 참고 자료입니다.</li>
        <li>실제 기록이 충분히 모이기 전까지 일부 결과는 예시 데이터로 계산됩니다. 예시 데이터는 실제 사람이 아닙니다.</li>
      </ul>

      <h2>3. 회원가입과 계정</h2>
      <p>회원가입과 로그인은 회사의 HMM ID(카카오 로그인)로 합니다. 이용자는 자기 정보를 정확히 입력해야 하며, 다른 사람의
        정보를 입력해서는 안 됩니다. 회원은 언제든지 탈퇴할 수 있습니다.</p>

      <h2>4. 튜브와 유료 카드</h2>
      <ul>
        <li>튜브는 결과 카드를 여는 데 쓰는 서비스 내 이용권입니다. 카드 1장을 여는 데 1튜브가 듭니다.</li>
        <li>회원가입 시 1튜브를 선물로 드립니다. 첫 번째 결과 카드는 무료입니다.</li>
        <li>튜브가 없으면 카드 1장을 <b>990원</b>(부가세 포함)에 결제해서 열 수 있습니다. 결제는 토스페이먼츠를 통해 카드·간편결제로 합니다.</li>
        <li>카드에 필요한 인원이 모자라 열 수 없으면 튜브를 쓰지 않으며, 결제한 튜브는 잔액으로 남습니다.</li>
        <li>정식 결제를 준비하는 동안에는 결제 화면에서 결제하기를 눌러도 실제로 결제되지 않으며, 결제 정보도 받지 않습니다.
          이때는 튜브 1개를 선물로 드려 그 카드를 엽니다(한 사람에 10개까지).</li>
        <li>튜브는 현금으로 바꾸거나 다른 사람에게 넘길 수 없습니다.</li>
      </ul>

      <h2>5. 청약철회와 환불</h2>
      <ul>
        <li>유료 카드는 결제 즉시 열리는 디지털 콘텐츠로, 열린 뒤에는 「전자상거래 등에서의 소비자보호에 관한 법률」 제17조
          제2항 제5호에 따라 청약철회가 제한됩니다. 결제 전 무료 카드로 내용을 미리 확인할 수 있습니다.</li>
        <li>결제했는데 카드가 열리지 않았거나 오류로 내용이 제공되지 않은 경우, 결제일로부터 7일 안에 알려주시면 전액 환불해 드립니다.</li>
        <li>결제 후 쓰지 않은 튜브는 결제일로부터 7일 안에 요청하면 환불해 드립니다.</li>
        <li>환불은 결제한 수단으로 취소 처리하며, 카드사 사정에 따라 3~7영업일이 걸릴 수 있습니다.</li>
        <li>문의: <a href="mailto:branden@da-sh.io">branden@da-sh.io</a></li>
      </ul>

      <h2>6. 이용자의 의무</h2>
      <p>서비스를 자동화된 방법으로 대량 조회하거나, 결과를 이용해 특정 개인을 알아내려 하거나, 다른 사람의 이력서·정보를 올려서는
        안 됩니다. 이를 어기면 이용을 제한할 수 있습니다.</p>

      <h2>7. 서비스 변경과 중단</h2>
      <p>회사는 서비스 내용을 바꾸거나 중단할 수 있으며, 유료 서비스에 영향을 주는 변경은 7일 전에 알립니다. 서비스를 중단할 때
        쓰지 않은 유료 튜브는 환불합니다.</p>

      <h2>8. 책임의 제한</h2>
      <p>결과는 비슷한 사람들의 기록을 묶은 통계이며 개인의 진로 결과를 보장하지 않습니다. 회사의 고의나 중과실이 없는 한,
        통계를 참고해 내린 결정의 결과에 대해서는 책임지지 않습니다.</p>

      <h2>9. 개인정보</h2>
      <p>개인정보 처리는 <a href="/privacy">개인정보처리방침</a>을 따릅니다.</p>

      <h2>10. 분쟁 해결</h2>
      <p>이 약관은 대한민국 법을 따르며, 분쟁은 민사소송법상 관할 법원에서 해결합니다. 이용자는 한국소비자원 등 분쟁조정기관에
        조정을 신청할 수 있습니다.</p>

      <p className="meta">변경 이력: {EFFECTIVE} 최초 시행</p>
      <footer><BusinessInfo /></footer>
    </main>
  );
}
