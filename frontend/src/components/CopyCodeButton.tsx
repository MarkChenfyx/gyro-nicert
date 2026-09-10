import React from "react";
import { Button, message } from "antd";

function copyWithFallback(text: string): boolean {
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  textarea.style.pointerEvents = "none";
  document.body.appendChild(textarea);
  textarea.select();

  try {
    return document.execCommand("copy");
  } finally {
    document.body.removeChild(textarea);
  }
}

export function CopyCodeButton({ code }: { code: string }) {
  async function copyCode() {
    if (!code) return;

    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(code);
      } else if (!copyWithFallback(code)) {
        throw new Error("copy command failed");
      }
      message.success("已复制完整策略代码");
    } catch {
      try {
        if (!copyWithFallback(code)) throw new Error("copy command failed");
        message.success("已复制完整策略代码");
      } catch {
        message.error("复制失败，请手动选择代码");
      }
    }
  }

  return (
    <Button size="small" disabled={!code.trim()} onClick={copyCode}>
      复制全部代码
    </Button>
  );
}
