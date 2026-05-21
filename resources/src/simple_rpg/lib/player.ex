defmodule Player do
  def join(game_server, name) do
    player_pid = spawn_link(fn -> player_loop(name) end)
    send(game_server, {:join, player_pid, name})
    player_pid
  end

  def play(game_server, name, hand) do
    send(game_server, {:play, name, hand})
  end

  defp player_loop(name) do
    receive do
      {:result, result} ->
        IO.puts("[#{name}] #{result}")
        :ok
    end
  end
end
