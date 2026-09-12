<template>
  <router-view v-slot="{ Component }">
    <transition name="fade-slide" mode="out-in">
      <component :is="Component" />
    </transition>
  </router-view>

  <!-- 全局 NProgress 占位（页面切换显示） -->
  <div id="nprogress-bar" ref="bar" style="position:fixed;top:0;left:0;right:0;z-index:9999;">
    <div :style="{ width: progress+'%', height: '2px', background: '#25D07D', transition: 'width .3s', opacity: showBar ? 1 : 0 }"></div>
  </div>
</template>

<script setup>
import { ref, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useUserStore } from '@/store/user'

const progress = ref(0)
const showBar = ref(false)
const route = useRoute()
const user = useUserStore()

onMounted(() => {
  user.tryRestoreLogin()
})

watch(
  () => route.fullPath,
  () => {
    showBar.value = true
    progress.value = 30
    setTimeout(() => { progress.value = 80 }, 120)
    setTimeout(() => {
      progress.value = 100
      setTimeout(() => { showBar.value = false; progress.value = 0 }, 200)
    }, 260)
  }
)
</script>

<style>
.fade-slide-enter-active,
.fade-slide-leave-active {
  transition: opacity .22s ease, transform .22s ease;
}
.fade-slide-enter-from {
  opacity: 0;
  transform: translateY(6px);
}
.fade-slide-leave-to {
  opacity: 0;
  transform: translateY(-6px);
}
</style>
