defmodule GameServer do
  def start_link do
    {:ok, spawn_link(fn -> game_loop(%{}) end)}
  end

  defp game_loop(players) do
    receive do
      {:join, player_pid, name} ->
        new_players = Map.put(players, name, %{pid: player_pid, hand: nil})
        game_loop(new_players)

      {:play, name, hand} ->
        updated = put_in(players[name][:hand], hand)
        check_and_announce(updated)

      :quit ->
        :ok
    end
  end

  defp check_and_announce(players) do
    if all_hands_ready?(players) do
      result = judge_game(players)
      Enum.each(players, fn {_name, %{pid: pid}} ->
        send(pid, {:result, result})
      end)
      game_loop(%{})
    else
      game_loop(players)
    end
  end

  defp all_hands_ready?(players) do
    Enum.all?(players, fn {_name, %{hand: hand}} -> hand != nil end)
  end

  defp judge_game(players) do
    hands = Map.new(players, fn {name, %{hand: hand}} -> {name, hand} end)

    hand_names = Enum.map(hands, fn {name, hand} ->
      "#{name}: #{hand_name(hand)}"
    end)
    |> Enum.join(", ")

    winners = find_winners(hands)
    winner_str = Enum.join(winners, ", ")

    "Result: #{hand_names} → #{winner_str}"
  end

  defp hand_name(hand) do
    case hand do
      1 -> "Rock"
      2 -> "Paper"
      3 -> "Scissors"
    end
  end

  defp find_winners(hands) do
    hand_values = hands |> Map.values() |> Enum.uniq()

    cond do
      length(hand_values) == 1 ->
        ["Draw!"]

      length(hand_values) == 2 ->
        [hand1, hand2] = Enum.sort(hand_values)

        if beats?(hand1, hand2) do
          winners = hands
            |> Enum.filter(fn {_name, h} -> h == hand1 end)
            |> Enum.map(fn {name, _} -> name end)
            |> Enum.join(", ")
          ["#{winners} win!"]
        else
          winners = hands
            |> Enum.filter(fn {_name, h} -> h == hand2 end)
            |> Enum.map(fn {name, _} -> name end)
            |> Enum.join(", ")
          ["#{winners} win!"]
        end

      true ->
        ["Three-way: Scissors beats Paper, Paper beats Rock, Rock beats Scissors - Draw!"]
    end
  end

  defp beats?(1, 2), do: false  # Paper beats Rock
  defp beats?(1, 3), do: true   # Rock beats Scissors
  defp beats?(2, 3), do: false  # Scissors beats Paper
  defp beats?(_, _), do: false
end
