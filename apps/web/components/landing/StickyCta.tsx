"use client";

import { useEffect, useState } from "react";

/** Phone-only bottom CTA, shown once the hero form has scrolled out of view. */
export default function StickyCta() {
  const [show, setShow] = useState(false);
  useEffect(() => {
    const form = document.getElementById("hero-form");
    if (!form || !("IntersectionObserver" in window)) return;
    const io = new IntersectionObserver(([e]) => setShow(!e.isIntersecting && e.boundingClientRect.top < 0));
    io.observe(form);
    return () => io.disconnect();
  }, []);
  return (
    <a className="sticky-cta" href="#hero-form" hidden={!show}>무료로 내 진로 지도 받기</a>
  );
}
