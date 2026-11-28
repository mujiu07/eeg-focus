/* ============================================================
   专注小蛙 · 档案头像素材 v1.9.5
   九张图片来自同一套纯头像素材；旧头像 ID 仅做兼容映射，
   不删除、不重写既有档案记录。
   ============================================================ */
(function (global) {
  "use strict";

  const LIST = Object.freeze([
    { id: "avatar_01", file: "avatar_01.png", label: "小蛙" },
    { id: "avatar_02", file: "avatar_02.png", label: "草帽蛙" },
    { id: "avatar_03", file: "avatar_03.png", label: "探险蛙" },
    { id: "avatar_04", file: "avatar_04.png", label: "音乐蛙" },
    { id: "avatar_05", file: "avatar_05.png", label: "围巾蛙" },
    { id: "avatar_06", file: "avatar_06.png", label: "皇冠蛙" },
    { id: "avatar_07", file: "avatar_07.png", label: "魔法蛙" },
    { id: "avatar_08", file: "avatar_08.png", label: "潜水蛙" },
    { id: "avatar_09", file: "avatar_09.png", label: "花花蛙" },
  ]);

  // v1.9.4 及更早版本写入的 ID 继续可读；只影响显示，不改数据库。
  const LEGACY = Object.freeze({
    frog: "avatar_01",
    tadpole: "avatar_01",
    lotus: "avatar_09",
    fish: "avatar_08",
    dragonfly: "avatar_03",
    snail: "avatar_02",
  });

  const BY_ID = Object.freeze(Object.fromEntries(LIST.map(a => [a.id, a])));

  function resolve(id) {
    const key = String(id || "");
    return BY_ID[key] || BY_ID[LEGACY[key]] || LIST[0];
  }

  function src(id) {
    return "assets/avatars/" + resolve(id).file;
  }

  function markup(id, className) {
    const avatar = resolve(id);
    const extra = className ? " " + className : "";
    return `<img class="avatar-img${extra}" src="${src(avatar.id)}" alt="" aria-hidden="true" draggable="false" data-avatar-id="${avatar.id}">`;
  }

  global.AvatarArt = Object.freeze({ LIST, LEGACY, resolve, src, markup });
})(window);
