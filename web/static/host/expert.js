// 专家模式：默认关闭。关闭时顶栏只显示日常入口（今天 / 项目 / 报告 / 工具 / 设置），
// 原始系统查询、交付物工作台、表单分析、诊断录制等技术向入口收起。
// 偏好只存在本机浏览器（localStorage），属于每个人自己的界面习惯。
import { createStore } from "./session.js";

const KEY = "vse.expertMode";

function readInitial() {
  try {
    return window.localStorage.getItem(KEY) === "1";
  } catch (_err) {
    return false;
  }
}

export const expertStore = createStore(typeof window === "undefined" ? false : readInitial());

function applyBodyClass(on) {
  if (typeof document !== "undefined" && document.body) document.body.classList.toggle("is-expert", on);
}

export function setExpertMode(on) {
  try {
    window.localStorage.setItem(KEY, on ? "1" : "0");
  } catch (_err) {
    // 隐私模式等情况下存不住，只在本次页面生效
  }
  expertStore.set(Boolean(on));
  applyBodyClass(Boolean(on));
}

if (typeof document !== "undefined") applyBodyClass(expertStore.get());
