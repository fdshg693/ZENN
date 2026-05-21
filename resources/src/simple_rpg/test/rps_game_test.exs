defmodule RpsGameTest do
  use ExUnit.Case
  doctest RpsGame

  test "greets the world" do
    assert RpsGame.hello() == :world
  end
end
