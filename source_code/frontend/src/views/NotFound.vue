<template>
  <div class="nf-page">
    <div class="nf-code">404</div>
    <div class="nf-text">页面不存在</div>
    <div class="nf-sub">您访问的页面可能已被删除或链接有误</div>
    <el-button type="primary" size="large" @click="$router.push('/dashboard')" style="margin-top: 30px;">
      <el-icon><House /></el-icon>
      返回首页
    </el-button>
  </div>
</template>

<script setup>
import { House } from '@element-plus/icons-vue'
</script>

<style lang="scss" scoped>
.nf-page {
  height: 100vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  background:
    radial-gradient(800px 500px at 50% 30%, rgba(37,208,125,0.08), transparent 60%),
    #0F1A24;
}
.nf-code {
  font-size: 160px;
  font-weight: 900;
  background: linear-gradient(135deg, #25D07D 0%, #60A5FA 100%);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  letter-spacing: 4px;
  font-family: "JetBrains Mono", Consolas, monospace;
  line-height: 1;
}
.nf-text {
  font-size: 28px;
  font-weight: 600;
  color: #F0F4F8;
  margin-top: 10px;
}
.nf-sub {
  font-size: 14px;
  color: #6B7C90;
  margin-top: 8px;
}
</style>
