package = "visdom"
version = "scm-1"

source = {
   url = "git://github.com/facebookresearch/visdom.git"
}

description = {
   summary = "A tool for visualizing live, rich data for Torch and Numpy.",
   detailed = [[
      A tool for visualizing live, rich data for Torch and Numpy.
   ]],
   homepage = "https://github.com/facebookresearch/visdom",
   license = "Creative Commons Attribution-NonCommercial 4.0 International Public License"
}

dependencies = {
   "lua >= 5.1",
   "torch >= 7.0",
   "argcheck >= 1.0",
   "luafilesystem >= 1.0",
   "torchnet >= 1.0",
   "image >= 1.0",
   "luasocket >= 1.0",
   "json >= 1.0",
   "luaffi >= 1.0",
}

build = {
   type = "cmake",
   cmake = [[
     cmake_minimum_required (VERSION 2.8)
     cmake_policy(VERSION 2.8)

     set(PKGNAME visdom)

     file(GLOB_RECURSE luafiles RELATIVE "${CMAKE_CURRENT_SOURCE_DIR}" "*.lua")

     foreach(file ${luafiles})
       install(FILES ${file} DESTINATION ${LUA_PATH}/${PKGNAME})
     endforeach()
   ]],
   variables = {
      CMAKE_BUILD_TYPE="Release",
      LUA_PATH="$(LUADIR)",
      LUA_CPATH="$(LIBDIR)"
   }
}
